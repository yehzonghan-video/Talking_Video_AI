from core.video.schemas import Decision, Transcript
from core.video.errors import VideoError


def validate_decisions(decisions: list[Decision], duration: float, transcript: Transcript | None):
    ids = {s.id for s in transcript.segments} if transcript else set()
    for item in decisions:
        if item.end > duration or any(s not in ids for s in item.segment_ids):
            raise VideoError('剪輯建議的時間或語音片段無效。')


def protected_speech(transcript: Transcript | None, start: float, end: float, padding: float) -> bool:
    return bool(transcript and any(start < s.end + padding and end > max(0, s.start - padding) for s in transcript.segments))
