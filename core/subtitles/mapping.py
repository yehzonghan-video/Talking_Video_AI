"""Piecewise source/output bijection on retained media only."""
from dataclasses import dataclass
from core.subtitles.schemas import Span, OutputCaption
from core.subtitles.segmentation import group_atoms, wrap
from core.video.errors import VideoError
from core.video.timeline import validate_timeline


@dataclass(frozen=True)
class Mapping:
    source_start: float
    source_end: float
    output_start: float
    output_end: float


def time_map(timeline):
    validate_timeline(timeline)
    pieces, cursor = [], 0.0
    for keep in timeline.keep_segments:
        length = keep.end - keep.start
        pieces.append(Mapping(keep.start, keep.end, cursor, cursor + length))
        cursor += length
    return pieces


def output_to_source(start, end, timeline):
    # Span rejects NaN, negative values and reversed bounds before any arithmetic.
    span = Span(start=start, end=end)
    pieces = time_map(timeline)
    if span.end > pieces[-1].output_end + .00001:
        raise VideoError('字幕時間超出剪輯後影片，請使用輸出時間調整。')
    return [Span(start=p.source_start + max(0, start - p.output_start),
                 end=p.source_start + min(p.output_end, end) - p.output_start)
            for p in pieces if min(end, p.output_end) - max(start, p.output_start) > .00001]


def map_captions(track, timeline):
    pieces, result = time_map(timeline), []
    for cue in track.cues:
        # Unedited acoustic words can be filtered precisely after a changed cut.
        if cue.atoms and not cue.manual:
            for part_index, p in enumerate(pieces):
                surviving = [a for a in cue.atoms if a.start >= p.source_start - .00001 and a.end <= p.source_end + .00001]
                partial = [a for a in cue.atoms if min(a.end, p.source_end) > max(a.start, p.source_start)
                           and a not in surviving]
                for index, group in enumerate(group_atoms(surviving)):
                    text = wrap(''.join(a.text for a in group))
                    reason = cue.review_reason or ('剪輯點切入詞語，請試聽並確認此處字幕。' if partial else '')
                    result.append(OutputCaption(id=f'{cue.id}:{part_index}:{index}',
                        start=p.output_start + group[0].start - p.source_start,
                        end=p.output_start + group[-1].end - p.source_start, text=text,
                        source_spans=[Span(start=group[0].start, end=group[-1].end)],
                        highlights=[h for h in cue.highlights if h in text.replace('\n', '')],
                        needs_review=bool(reason), review_reason=reason))
                if partial and not surviving:
                    a, b = max(min(a.start for a in partial), p.source_start), min(max(a.end for a in partial), p.source_end)
                    result.append(OutputCaption(id=f'{cue.id}:{part_index}:partial', start=p.output_start + a - p.source_start,
                        end=p.output_start + b - p.source_start, text=cue.text, source_spans=[Span(start=a, end=b)],
                        needs_review=True, review_reason='剪輯點切入詞語，請手動確認字幕或調整剪輯點。'))
            continue
        mapped = []
        for span in cue.spans:
            for p in pieces:
                a, b = max(span.start, p.source_start), min(span.end, p.source_end)
                if b > a + .00001:
                    mapped.append((p.output_start + a - p.source_start, p.output_start + b - p.source_start, Span(start=a, end=b)))
        if not mapped:
            continue
        mapped.sort(key=lambda m: m[0])
        lost = sum(s.end - s.start for s in cue.spans) - sum(m[1] - m[0] for m in mapped) > .001
        gap = any(b[0] - a[1] > .001 for a, b in zip(mapped, mapped[1:]))
        reason = cue.review_reason or ('剪輯改變了這段字幕涵蓋的內容，請保留修字並重新確認分段。' if lost or gap else '')
        result.append(OutputCaption(id=cue.id, start=mapped[0][0], end=mapped[-1][1], text=cue.text,
            source_spans=[m[2] for m in mapped], highlights=cue.highlights,
            needs_review=bool(reason), review_reason=reason))
    result.sort(key=lambda c: (c.start, c.end))
    return result


def validate_output(cues, duration, require_reviewed=False):
    previous = 0.0
    for cue in cues:
        if cue.start < previous - .00001 or cue.end > duration + .00001:
            raise VideoError('字幕時間重疊或超出剪輯後影片，請調整後保存。')
        if require_reviewed and cue.needs_review:
            raise VideoError('有字幕因剪輯或時間資料不足需要確認，請先修正並勾選確認後保存。')
        if not cue.text.strip():
            raise VideoError('字幕內容不可空白；不需要的字幕請刪除整列。')
        previous = cue.end
