from pathlib import Path
from uuid import uuid4
from contextlib import ExitStack
from core.video.schemas import Timeline, MediaInfo
from core.video.assets import sha256
from core.video.ffmpeg import run
from core.video.media_probe import probe
from core.video.timeline import validate_timeline
from core.video.errors import VideoError


def render(source: Path, output: Path, timeline: Timeline, media: MediaInfo, expected_sha: str,
           preview: bool = False, progress=None, *, subtitles=None, subtitle_style=None) -> Path:
    validate_timeline(timeline)
    source, output = source.resolve(), output.resolve()
    if source == output or output.exists():
        raise VideoError('輸出檔已存在或指向原片，不允許覆蓋；請產生新輸出。')
    if sha256(source) != expected_sha:
        raise VideoError('原片內容已變更，停止輸出以避免剪錯影片。')
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / ('temp-render-' + uuid4().hex + '.mp4')
    script = output.parent / ('temp-filter-' + uuid4().hex + '.txt')
    count = len(timeline.keep_segments)
    fps = min(60, max(1, round(media.fps, 3)))
    # Normalize cadence before trimming: old FFmpeg versions can retain the input EOF
    # timestamp in a post-trim fps filter and duplicate frames across removed ranges.
    scale = "scale=w='trunc(iw*sar/2)*2':h='trunc(ih/2)*2',setsar=1"
    if preview:
        scale += ",scale=w='trunc(iw*min(1,640/ih)/2)*2':h='trunc(ih*min(1,640/ih)/2)*2'"
    filters = [f'[0:v:0]{scale},fps=fps={fps},split={count}' + ''.join(f'[vs{i}]' for i in range(count))]
    if media.audio_codec:
        filters.append(f'[0:a:0]asplit={count}' + ''.join(f'[as{i}]' for i in range(count)))
    for i, item in enumerate(timeline.keep_segments):
        length = item.end - item.start
        # FFmpeg autorotates phone display matrices before these filters. Normalize non-square pixels.
        filters.append(f'[vs{i}]trim=start={item.start:.6f}:end={item.end:.6f},setpts=PTS-STARTPTS[v{i}]')
        if media.audio_codec:
            audio = f'[as{i}]atrim=start={item.start:.6f}:end={item.end:.6f},asetpts=PTS-{item.start:.6f}/TB,aresample=48000:async=1:first_pts=0'
        else:
            audio = 'anullsrc=r=48000:cl=stereo'
        filters.append(audio + f',apad=whole_dur={length:.6f},atrim=duration={length:.6f},aformat=sample_fmts=fltp:channel_layouts=stereo,'
            f'afade=t=in:d=0.008,afade=t=out:st={max(0, length - .008):.6f}:d=0.008[a{i}]')
    filters.append(''.join(f'[v{i}][a{i}]' for i in range(count)) + f'concat=n={count}:v=1:a=1' + ('[vbase][a]' if subtitles else '[v][a]'))
    resources = ExitStack()
    try:
        if subtitles:
            from core.subtitles.burn import burn_filter
            from core.subtitles.schemas import CaptionStyle
            duration = sum(s.end - s.start for s in timeline.keep_segments)
            overlay = resources.enter_context(burn_filter(output.parent, subtitles, subtitle_style or CaptionStyle(), media, duration))
            filters.append(f'[vbase]{overlay}[v]')
        script.write_text(';\n'.join(filters), encoding='utf-8')
        if progress:
            progress('正在重新編碼並串接片段，請稍候', .2)
        run('ffmpeg', ['-v', 'error', '-nostdin', '-filter_complex_threads', '2', '-copyts', '-start_at_zero', '-i', str(source),
            '-filter_complex_script', str(script), '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast' if preview else 'fast', '-crf', '26' if preview else '20',
            '-vsync', '0', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
            '-metadata:s:v:0', 'rotate=0', '-movflags', '+faststart', str(work)], timeout=1800, cwd=output.parent)
        info = probe(work, decode=True)
        expected_duration = sum(s.end - s.start for s in timeline.keep_segments)
        if abs(info.duration - expected_duration) > max(.15, count / fps + .05):
            raise VideoError('輸出長度驗證失敗，請檢查片段邊界後重試。')
        if info.video_codec != 'h264' or info.audio_codec != 'aac':
            raise VideoError('輸出編碼驗證失敗。')
        if info.audio_start is not None and abs(info.video_start - info.audio_start) > .1:
            raise VideoError('輸出音畫起點不同步，請重新輸出。')
        if info.video_duration is not None and info.audio_duration is not None and abs(info.video_duration - info.audio_duration) > .15:
            raise VideoError('輸出音畫長度不同步，請重新輸出。')
        if sha256(source) != expected_sha:
            raise VideoError('處理過程中原片被外部修改，停止交付輸出。')
        # Atomic publish, no overwrite. work is always in the same filesystem as output.
        work.rename(output)
        if progress:
            progress('影片輸出完成', 1.0)
        return output
    finally:
        resources.close()
        script.unlink(missing_ok=True)
        work.unlink(missing_ok=True)
