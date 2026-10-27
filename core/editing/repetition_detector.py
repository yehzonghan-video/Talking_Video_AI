from core.editing.script_matcher import normalize, similarity
from core.video.schemas import Transcript, Decision


def detect_repetitions(transcript: Transcript) -> list[Decision]:
    """Flag nearby sentence and multi-sentence retakes. Always preserve until confirmed."""
    segments = transcript.segments
    results, covered = [], set()
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
