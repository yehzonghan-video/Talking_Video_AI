"""Supplement only long segments lacking usable word times; keep original ASR."""
from uuid import uuid4
from core.subtitles.segmentation import from_transcript
from core.transcription.alignment import validate_transcript
from core.video.schemas import Segment
from core.video.ffmpeg import run
from core.video.assets import sha256
from core.video.errors import VideoError


def supplement(project, assets, provider):
    original = project.transcript
    if not original:
        raise VideoError('請先完成語音辨識。')
    if sha256(assets.source(project)) != project.source_sha256:
        raise VideoError('原片已變更，無法補充字幕時間。')
    result = original.model_copy(deep=True)
    segments = []
    for segment in original.segments:
        one = original.model_copy(update={'segments': [segment]})
        needs = any(c.review_reason and not c.atoms for c in from_transcript(one))
        if not needs:
            segments.append(segment.model_copy(deep=True))
            continue
        audio = assets.path(project.id, 'temp-sub-align-' + uuid4().hex + '.wav')
        duration = segment.end - segment.start
        try:
            run('ffmpeg', ['-v', 'error', '-nostdin', '-ss', str(segment.start), '-i', str(assets.source(project)),
                '-t', str(duration), '-vn', '-map', '0:a:0', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(audio)])
            aligned = provider.transcribe(audio, duration)
            validate_transcript(aligned, duration)
            if not aligned.segments:
                raise VideoError('補充時間時沒有辨識到語音，原有辨識與字幕均保留。')
            for i, item in enumerate(aligned.segments):
                words = [w.model_copy(update={'start': w.start + segment.start, 'end': w.end + segment.start}) for w in item.words]
                segments.append(Segment(id=f'caption_{segment.id}_{i}', start=item.start + segment.start,
                    end=item.end + segment.start, text=item.text, words=words))
        finally:
            audio.unlink(missing_ok=True)
    result.segments = segments
    validate_transcript(result, project.media.duration)
    return result
