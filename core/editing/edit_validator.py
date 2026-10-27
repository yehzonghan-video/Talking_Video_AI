from core.video.schemas import Decision, Transcript
from core.video.errors import VideoError


def validate_decisions(decisions: list[Decision], duration: float, transcript: Transcript | None):
    ids = {s.id for s in transcript.segments} if transcript else set()
    for item in decisions:
        if item.end > duration or any(s not in ids for s in item.segment_ids):
            raise VideoError('剪輯建議的時間或語音片段無效。')
        if item.kind != 'silence' and (not item.requires_review or item.selected and not item.confirmed):
            raise VideoError('語音刪除建議必須保留人工確認。')
        if item.kind == 'silence' and item.selected and not item.requires_review:
            if not transcript or protected_speech(transcript, item.start, item.end, .08):
                raise VideoError('自動縮短停頓缺少聲學依據或碰到語音邊界，請改為人工確認。')


def protected_speech(transcript: Transcript | None, start: float, end: float, padding: float) -> bool:
    return bool(transcript and any(start < s.end + padding and end > max(0, s.start - padding) for s in transcript.segments))
