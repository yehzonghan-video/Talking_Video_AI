"""Lexical evidence is a hint, never a reason to delete speech."""
from difflib import SequenceMatcher
import re
import unicodedata
from core.video.schemas import Match, Transcript


def normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text) if c.isalnum()).lower()


def script_sentences(script: str) -> list[str]:
    return [line.strip() for line in re.split(r'[。！？!?\n]+', script) if line.strip()]


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()


def match_script(script: str, transcript: Transcript) -> list[Match]:
    result = []
    for i, sentence in enumerate(script_sentences(script)):
        scored = [(similarity(sentence, seg.text), seg.id) for seg in transcript.segments]
        scored.sort(reverse=True)
        best = scored[0] if scored else (0, '')
        status = 'matched' if best[0] >= .65 else 'needs_review'
        result.append(Match(script_index=i, script_text=sentence, segment_ids=[best[1]] if best[0] >= .25 else [],
                            status=status, reason='文字相近，請搭配原片確認。' if status == 'matched' else '文字差異不能視為口誤，可能是口語改寫或漏講，需人工確認。'))
    return result
