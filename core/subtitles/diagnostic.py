"""Disposable smoke check; no user media, database, ASR or AI calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from core.subtitles.fonts import subtitle_capabilities
from core.subtitles.schemas import SubtitleTrack, CaptionStyle
from core.subtitles.mapping import map_captions
from core.subtitles.formats import srt
from core.subtitles.segmentation import from_transcript
from core.video.ffmpeg import run
from core.video.media_probe import probe
from core.video.assets import sha256
from core.video.timeline import build_timeline
from core.video.schemas import Decision, Transcript, Segment, Word
from core.video.renderer import render


def inspect_environment(folder):
    font = subtitle_capabilities('繁體字幕室內設計剪輯後時間同步')
    with TemporaryDirectory(prefix='temp-caption-check-', dir=folder) as temporary:
        root = Path(temporary).resolve()
        source, burned, plain, frame = (root / n for n in ('source.mp4', 'captioned.mp4', 'plain.mp4', 'frame.png'))
        run('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=192x320:r=25:d=3',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'libx264', '-threads', '2', '-preset', 'ultrafast',
            '-c:a', 'aac', '-shortest', str(source)])
        media = probe(source)
        timeline = build_timeline(media.duration, [Decision(start=1, end=2, kind='manual', reason='字幕環境測試', selected=True, confirmed=True)], 2, '字幕環境測試')
        transcript = Transcript(provider='environment-test', model='synthetic', timing='acoustic-alignment', segments=[
            Segment(id='a', start=.1, end=.9, text='繁体字幕室内设计', words=[
                Word(start=.1, end=.4, text='繁体字幕'), Word(start=.4, end=.9, text='室内设计')]),
            Segment(id='b', start=1.1, end=1.9, text='删除这段', words=[Word(start=1.1, end=1.9, text='删除这段')]),
            Segment(id='c', start=2.1, end=2.9, text='剪辑后时间同步', words=[Word(start=2.1, end=2.9, text='剪辑后时间同步')])])
        track = SubtitleTrack(source_signature='0' * 64, cues=from_transcript(transcript))
        for cue in track.cues:
            if '室內設計' in cue.text.replace('\n', ''):
                cue.highlights = ['室內設計']
        cues = map_captions(track, timeline)
        render(source, burned, timeline, media, sha256(source), subtitles=cues, subtitle_style=CaptionStyle(preset='emphasis', font_size=72))
        render(source, plain, timeline, media, sha256(source))
        run('ffmpeg', ['-v', 'error', '-ss', '0.5', '-i', str(burned), '-vf', 'scale=360:-2', '-frames:v', '1', str(frame)])
        return {'font': font.family, 'captioned': burned.read_bytes(), 'plain': plain.read_bytes(),
                'frame': frame.read_bytes(), 'srt': srt(cues, 2).encode('utf-8-sig'), 'duration': probe(burned).duration,
                'source': source.read_bytes(), 'transcript': transcript.model_dump(), 'media': media.model_dump()}
