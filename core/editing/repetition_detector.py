from core.editing.script_matcher import normalize, similarity, script_sentences
from core.video.schemas import Transcript, Decision


def _common_prefix(left: str, right: str) -> int:
    return next((index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]), min(len(left), len(right)))


def _script_fit(text: str, sentences: list[str]) -> float:
    return max((similarity(text, sentence) for sentence in sentences), default=0.0)


def _automatic_retake_decisions(transcript: Transcript, script: str) -> list[Decision]:
    """Remove only an earlier, clearly abandoned start of the same sentence.

    This deliberately needs both a long common opening and evidence that a later
    take is more complete (normally a materially better script match). Exact
    repetitions are left alone because they can be intentional emphasis.
    """
    sentences = script_sentences(script)
    segments, results, claimed = transcript.segments, [], set()
    for start, first in enumerate(segments):
        if first.id in claimed:
            continue
        window = [first]
        for later in segments[start + 1:start + 4]:
            if later.start - window[-1].end > 20:
                break
            base, candidate = normalize(first.text), normalize(later.text)
            if len(base) < 6 or len(candidate) < 6 or _common_prefix(base, candidate) < 6:
                break
            window.append(later)
        if len(window) < 2:
            continue

        # A complete take should agree with the saved script substantially more
        # than an aborted one. Length is only a tie-breaker: it must never make
        # a less script-like final attempt win merely because it is longer.
        fits = [_script_fit(segment.text, sentences) for segment in window]
        best_index = max(range(len(window)), key=lambda index: (fits[index], len(normalize(window[index].text)), index))
        best, best_fit = window[best_index], fits[best_index]
        if best_index == 0 or best_fit < .62:
            continue
        for index, earlier in enumerate(window[:best_index]):
            old = normalize(earlier.text)
            new = normalize(best.text)
            if old == new or earlier.id in claimed:
                continue  # Same complete wording may be deliberate emphasis.
            clearly_better = best_fit >= fits[index] + .12
            clearly_extended = new.startswith(old) and len(new) >= len(old) + 4 and best_fit >= .68
            if not (clearly_better or clearly_extended):
                continue
            results.append(Decision(start=earlier.start, end=earlier.end, kind='retake', action='remove',
                reason='高信心口誤重講：較後版本與腳本更完整相符，已自動保留後段版本。',
                requires_review=False, selected=True, segment_ids=[earlier.id]))
            claimed.add(earlier.id)
    return results


def detect_repetitions(transcript: Transcript, script: str = '') -> list[Decision]:
    """Select only high-confidence abandoned retakes; leave all uncertainty visible."""
    segments = transcript.segments
    results = _automatic_retake_decisions(transcript, script)
    covered = {segment_id for decision in results for segment_id in decision.segment_ids}
    # Paragraph restarts: repeated windows of two or three consecutive segments.
    for width in (3, 2):
        for i in range(len(segments) - width):
            old = segments[i:i + width]
            left = ''.join(s.text for s in old)
            if len(normalize(left)) < 16:
                continue
            for j in range(i + width, min(len(segments) - width + 1, i + width + 8)):
                new = segments[j:j + width]
                if new[0].start - old[-1].end > 90:
                    continue
                if similarity(left, ''.join(s.text for s in new)) >= .72:
                    ids = [s.id for s in old]
                    if not set(ids).intersection(covered):
                        results.append(Decision(start=old[0].start, end=old[-1].end, kind='retake',
                            reason='前後多句內容相近，可能為整段重講。請比較兩次內容完整度後決定。', segment_ids=ids))
                        covered.update(ids)
                    break
    for i, old in enumerate(segments):
        a = normalize(old.text)
        if len(a) < 6 or old.id in covered:
            continue
        for new in segments[i + 1:i + 7]:
            b = normalize(new.text)
            if new.start - old.end > 60:
                break
            prefix = len(a) >= 6 and len(b) >= len(a) and b.startswith(a)
            if prefix or similarity(a, b) >= .75:
                results.append(Decision(start=old.start, end=old.end, kind='retake' if prefix and a != b else 'repetition',
                    reason=f'疑似較早的重講片段，後方 {new.start:.2f} 秒有相近內容；也可能是刻意強調，預設保留。', segment_ids=[old.id]))
                break
    return results
