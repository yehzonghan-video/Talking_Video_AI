import json
from fractions import Fraction
from pathlib import Path
from core.video.ffmpeg import run
from core.video.schemas import MediaInfo
from core.video.errors import VideoError


def probe(path: Path, decode: bool = False) -> MediaInfo:
    try:
        raw = json.loads(run('ffprobe', ['-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], 60).stdout)
        video = next(s for s in raw['streams'] if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic'))
        audio = next((s for s in raw['streams'] if s.get('codec_type') == 'audio'), None)
        fmt = raw['format']['format_name']
        if not {'mov', 'mp4'}.intersection(fmt.split(',')):
            raise VideoError('目前僅接受真正的 MP4／MOV 容器，請先轉存為支援格式。')
        rotation = int(float(video.get('tags', {}).get('rotate', 0)))
        for side in video.get('side_data_list', []):
            if 'rotation' in side:
                rotation = int(round(float(side['rotation'])))
        w, h = int(video['width']), int(video['height'])
        sar = Fraction(video.get('sample_aspect_ratio', '1:1').replace(':', '/')) if video.get('sample_aspect_ratio') not in (None, 'N/A', '0:1') else Fraction(1)
        display_w, display_h = round(w * sar), h
        if rotation % 180:
            display_w, display_h = display_h, display_w
        fps = float(Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate', '30/1')))
        result = MediaInfo(duration=float(raw['format']['duration']), width=w, height=h,
            display_width=display_w, display_height=display_h, rotation=rotation, fps=fps,
            size=path.stat().st_size, format_name=fmt, video_codec=video['codec_name'],
            audio_codec=audio.get('codec_name') if audio else None,
            audio_start=float(audio.get('start_time', 0)) if audio else None,
            video_start=float(video.get('start_time', 0)),
            video_duration=float(video['duration']) if video.get('duration') not in (None, 'N/A') else None,
            audio_duration=float(audio['duration']) if audio and audio.get('duration') not in (None, 'N/A') else None)
        if decode:
            run('ffmpeg', ['-v', 'error', '-xerror', '-nostdin', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'], 900)
        return result
    except (ValueError, KeyError, StopIteration, TypeError, ZeroDivisionError) as exc:
        raise VideoError('影片資訊無效、超過15分鐘，或找不到可解碼的畫面；請重新選擇影片。') from exc
