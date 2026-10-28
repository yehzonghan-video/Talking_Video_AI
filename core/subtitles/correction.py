"""Conservative, auditable script hints. Never alter the acoustic transcript."""
from difflib import SequenceMatcher
import re
from uuid import uuid5, NAMESPACE_URL
from core.subtitles.schemas import ScriptCorrection
from core.subtitles.segmentation import traditional, lexical, wrap
from core.editing.script_matcher import script_sentences

# Reviewed confusion classes, not a general rewriting engine. Near sounds and
# unknown substitutions are suggestions only. Extend these dictionaries with tests.
HOMOPHONES = [set(x) for x in ('成層', '黃潢', '那納', '才材', '堅間')]
NEAR_SOUNDS = [set(x) for x in ('色設', '現線', '丈障', '梁樑')]
DOMAIN = ('收納', '裝潢', '空間', '建材', '設計', '動線', '隔間')
FACTS = re.compile(r'[零〇一二三四五六七八九十百千萬億兩0-9]+(?:[.．點][0-9]+)?|[%％元圓坪]|公分|公尺|毫米|厘米|釐米|公斤|日期|年|月|日')


def normalized(text):
    return ''.join(c for c in traditional(text).replace('\n', '') if c.isalnum() or c in '%％.')


def facts(text):
    return FACTS.findall(normalized(text))


def analyze_cue(cue, script):
    original = cue.text.replace('\n', '')
    source = normalized(original)
    candidates = [traditional(s) for s in script_sentences(script)]
    # Align to the matching script window, not the whole document or a missing line.
    scored = []
    for sentence in candidates:
        target = normalized(sentence)
        if not source or not target:
            continue
        if len(target) > len(source) + 8:
            match = SequenceMatcher(None, source, target, autojunk=False).find_longest_match()
            start = max(0, match.b - match.a)
            target = target[start:start + len(source)]
        scored.append((SequenceMatcher(None, source, target, autojunk=False).ratio(), target, sentence))
    score, target, reference = max(scored, default=(0, '', ''), key=lambda x: x[0])
    status, decision, proposed = 'keep', 'rejected', original
    reason = '與腳本不同或證據不足，保留實際辨識，不補入漏講內容。'
    if target == source:
        reason = '文字與參考腳本一致，保留實際辨識。'
    elif score >= .72:
        diffs = [op for op in SequenceMatcher(None, source, target, autojunk=False).get_opcodes() if op[0] != 'equal']
        same_length = len(source) == len(target) and all(tag == 'replace' and b - a == d - c == 1 for tag, a, b, c, d in diffs)
        if same_length and 1 <= len(diffs) <= 2:
            replacements = [(source[a:b], target[c:d]) for _, a, b, c, d in diffs]
            phonetic = all(any({a, b} <= group for group in HOMOPHONES + NEAR_SOUNDS) for a, b in replacements)
            protected = facts(source) != facts(target)
            domain_context = score >= .88 and any(word in target for word in DOMAIN)
            if phonetic or protected or domain_context:
                # Transfer only aligned substitutions; preserve original punctuation.
                positions = [i for i, char in enumerate(original) if char.isalnum() or char in '%％.']
                chars = list(original)
                for _, a, b, c, d in diffs:
                    chars[positions[a]] = target[c]
                proposed = ''.join(chars)
                strong = (score >= .88 and len(source) - len(diffs) >= 10 and not protected
                          and all(any({a, b} <= group for group in HOMOPHONES) for a, b in replacements)
                          and any(word in target for word in DOMAIN))
                status, decision = ('auto', 'accepted') if strong else ('review', 'pending')
                reason = ('同音字、強文字對齊與產業詞語證據一致；未改動數字或單位。' if strong else
                          '涉及數字／尺寸／事實差異，必須試聽確認。' if protected else '可能是近音字或專有詞誤辨，請試聽後確認。')
        elif facts(source) != facts(target) and score >= .8:
            status, decision = 'review', 'pending'
            reason = '數字或單位與腳本不同；保留辨識，不能按原稿補寫，請手動核對。'
    return ScriptCorrection(id=str(uuid5(NAMESPACE_URL, cue.id + source + target)), cue_id=cue.id,
        original=original, proposed=proposed, reference=reference, status=status, decision=decision, reason=reason)


def variant(cue, correction, decision):
    result = cue.model_copy(deep=True)
    result.correction_ref = correction.id
    if decision != 'accepted' or correction.status == 'keep':
        return result
    result.text = wrap(correction.proposed)
    if correction.status == 'review':
        result.manual = True  # An explicit fact/ambiguity confirmation is a user choice.
    # Same-length, aligned characters retain the exact original word times.
    flat = ''.join(a.text for a in result.atoms)
    if result.atoms and normalized(flat) == normalized(correction.original) and len(normalized(flat)) == len(normalized(correction.proposed)):
        changes = {i: b for i, (a, b) in enumerate(zip(normalized(flat), normalized(correction.proposed))) if a != b}
        cursor = 0
        for atom in result.atoms:
            chars = list(atom.text)
            for i, char in enumerate(chars):
                if char.isalnum() or char in '%％.':
                    if cursor in changes:
                        chars[i] = changes[cursor]
                    cursor += 1
            atom.text = ''.join(chars)
    elif result.atoms:
        result.atoms = []
        result.manual = True  # No invented within-word timing for a changed length.
    return result


def prepare_track(track, script):
    """Return a copy: raw analysis, correction decisions and manual edits stay distinct."""
    result = track.model_copy(deep=True)
    if result.corrections:
        return result
    result.original_cues = [c.model_copy(deep=True) for c in result.cues]
    result.corrections = [analyze_cue(c, script) for c in result.original_cues if not c.manual]
    by_id = {c.cue_id: c for c in result.corrections}
    result.cues = [variant(c, by_id[c.id], by_id[c.id].decision) if c.id in by_id else c for c in result.cues]
    return result
