"""Small, disposable ASS/font assets shared by preview and MP4 rendering."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from core.subtitles.fonts import subtitle_capabilities
from core.subtitles.formats import ass
from core.video.ffmpeg import run
from core.video.errors import VideoError
from core.subtitles.mapping import time_map
from core.video.assets import sha256


@contextmanager
def burn_filter(folder, cues, style, media, duration):
    font = subtitle_capabilities(''.join(c.text for c in cues))
    # Only generated ASCII names enter FFmpeg's filter grammar. User paths remain
    # argv values; copying one font avoids Windows drive/quote escaping failures.
    with TemporaryDirectory(prefix='temp-sub-', dir=folder) as temporary:
        root = Path(temporary)
        fonts = root / 'fonts'
        fonts.mkdir()
        shutil.copyfile(font.path, fonts / ('caption' + font.path.suffix))
        (root / 'captions.ass').write_text(ass(cues, style, font, media.display_width, media.display_height, duration), encoding='utf-8')
        yield f"ass=filename='{root.name}/captions.ass':fontsdir='{root.name}/fonts'"


def preview_frame(project, assets, cue, cues, style, output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if sha256(assets.source(project)) != project.source_sha256:
        raise VideoError('原片已變更，停止字幕預覽；請先重新連結正確原片。')
    if output.exists():
        return output
    moment = (cue.start + cue.end) / 2
    mapping = next((p for p in time_map(project.timelines[-1]) if p.output_start <= moment < p.output_end), None)
    if mapping is None:
        raise VideoError('找不到此段字幕對應的原片時間。')
    original = mapping.source_start + moment - mapping.output_start
    duration = time_map(project.timelines[-1])[-1].output_end
    with burn_filter(output.parent, cues, style, project.media, duration) as overlay:
        filters = f"scale=w='trunc(iw*sar/2)*2':h='trunc(ih/2)*2',setsar=1,scale=-2:640,setpts=PTS-STARTPTS+{moment:.6f}/TB,{overlay}"
        try:
            run('ffmpeg', ['-v', 'error', '-nostdin', '-ss', str(original), '-i', str(assets.source(project)),
                '-vf', filters, '-frames:v', '1', '-threads', '1', str(output)], cwd=output.parent)
        except Exception:
            output.unlink(missing_ok=True)
            raise
    return output


def prune_previews(assets, project_id, keep=3, preserve=None):
    files = sorted((p for p in assets.project_dir(project_id).glob('preview-*') if p.is_file() and not p.is_symlink()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    preserved = Path(preserve).resolve() if preserve is not None else None
    others = [p for p in files if p.resolve() != preserved]
    allowance = keep - int(any(p.resolve() == preserved for p in files))
    for path in others[max(0, allowance):]:
        try:
            path.unlink()
        except OSError:
            pass  # An open player may temporarily hold the file on Windows.
