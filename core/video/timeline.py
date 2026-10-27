import re
from core.video.schemas import Interval, Decision, Timeline
from core.video.errors import VideoError


def merge_intervals(intervals: list[Interval], duration: float) -> list[Interval]:
    merged = []
    for item in sorted(intervals, key=lambda i: i.start):
        if item.end > duration + 0.00001:
            raise VideoError('剪輯區間超出影片長度。')
        if merged and item.start <= merged[-1].end + 0.00001:
            merged[-1] = Interval(start=merged[-1].start, end=max(merged[-1].end, item.end))
        else:
            merged.append(item.model_copy(deep=True))
    return merged


def build_timeline(duration: float, decisions: list[Decision], number: int, note: str) -> Timeline:
    if duration <= 0:
        raise VideoError('影片長度必須大於零。')
    cuts = []
    for item in decisions:
        if item.end > duration:
            raise VideoError('剪輯區間超出影片長度。')
        if item.selected:
            if item.requires_review and not item.confirmed:
                raise VideoError('涉及語音或不確定的片段必須逐項確認後才能刪除。')
            cuts.append(Interval(start=item.start, end=item.end))
    cuts = merge_intervals(cuts, duration)
    keep, cursor = [], 0.0
    for cut in cuts:
        if cut.start > cursor:
            keep.append(Interval(start=cursor, end=cut.start))
        cursor = cut.end
    if cursor < duration:
        keep.append(Interval(start=cursor, end=duration))
    if not keep or sum(k.end - k.start for k in keep) < 0.1:
        raise VideoError('不能刪除全部影片；請至少保留0.1秒。')
    if len(keep) > 200:
        raise VideoError('片段超過200段，請合併部分剪輯後再試。')
    return Timeline(number=number, duration=duration, keep_segments=keep,
                    decisions=[d.model_copy(deep=True) for d in decisions], note=note)


def validate_timeline(timeline: Timeline) -> None:
    expected = build_timeline(timeline.duration, timeline.decisions, timeline.number, timeline.note)
    if expected.keep_segments != timeline.keep_segments:
        raise VideoError('保留片段與剪輯決策不一致，請重新確認時間軸。')


def filename(title: str) -> str:
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title).strip(' .')[:100] or '口播影片'
    if title.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        title = '_' + title
    return title + '_粗剪.mp4'
