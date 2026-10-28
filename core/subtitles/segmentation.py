"""Linguistic boundaries + measured pauses. Never invent per-character times."""
from functools import lru_cache
import logging
import re
import unicodedata
from core.subtitles.schemas import Atom, SourceCaption, Span


@lru_cache(maxsize=1)
def converter():
    from opencc import OpenCC
    return OpenCC('s2twp')


def traditional(text):
    return converter().convert(unicodedata.normalize('NFC', text)).strip()


@lru_cache(maxsize=1)
def tokenizer():
    import jieba
    jieba.setLogLevel(logging.ERROR)
    return jieba.Tokenizer()


def tokens(text):
    # Retain punctuation and spaces; segmentation changes layout, never wording.
    simplified = simplified_converter().convert(text)
    if len(simplified) != len(text):
        return list(tokenizer().cut(text, HMM=False))
    result, cursor = [], 0
    for token in tokenizer().cut(simplified, HMM=False):
        result.append(text[cursor:cursor + len(token)])
        cursor += len(token)
    return result


@lru_cache(maxsize=1)
def simplified_converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def width(text):
    return sum(1 if unicodedata.east_asian_width(c) in ('W', 'F') else .5 for c in text if c != '\n')


def wrap(text, limit=12):
    lines, current = [], ''
    for token in tokens(text.replace('\n', '')):
        if current and width(current + token) > limit and not re.fullmatch(r'[，。！？；：、,.!?;:]+', token):
            lines.append(current.strip())
            current = ''
        current += token
    if current.strip():
        lines.append(current.strip())
    return '\n'.join(lines)


def lexical(text):
    return ''.join(c for c in traditional(text) if c.isalnum())


def group_atoms(atoms):
    """Choose real word boundaries using punctuation, measured gaps and reading load."""
    groups, cursor = [], 0
    text = ''.join(a.text for a in atoms)
    boundaries, total = set(), 0
    for token in tokens(text):
        total += len(token)
        boundaries.add(total)
    offsets, total = [], 0
    for atom in atoms:
        total += len(atom.text)
        offsets.append(total)
    while cursor < len(atoms):
        choices, combined = [], ''
        stop = cursor
        for i in range(cursor, len(atoms)):
            combined += atoms[i].text
            duration = atoms[i].end - atoms[cursor].start
            gap = atoms[i + 1].start - atoms[i].end if i + 1 < len(atoms) else 0
            hard = bool(re.search(r'[。！？!?]$', atoms[i].text)) or gap >= .45
            natural = offsets[i] in boundaries or hard or i == len(atoms) - 1
            fits = len(wrap(combined).splitlines()) <= 2
            if fits and natural:
                score = -abs(width(combined) - 18) + min(gap, 1) * 12
                if re.search(r'[，。！？；、,.!?;]$', atoms[i].text):
                    score += 6
                if duration < .8:
                    score -= 8
                choices.append((score, i))
            stop = i
            if hard and duration >= .8 and width(combined) >= 4 and fits:
                break
            if not fits or duration > 6:
                stop = max(choices)[1] if choices else max(cursor, i - 1)
                break
        group = atoms[cursor:stop + 1]
        # Preserve a long indivisible word and flag it rather than making up times.
        groups.append(group)
        cursor = stop + 1
    # Avoid flicker when a short final fragment fits the preceding natural block.
    merged = []
    for group in groups:
        if (merged and group[-1].end - group[0].start < .7 and group[0].start - merged[-1][-1].end < .25
                and len(wrap(''.join(a.text for a in merged[-1] + group)).splitlines()) <= 2
                and group[-1].end - merged[-1][0].start <= 6):
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def cue_from_atoms(atoms):
    text = wrap(''.join(a.text for a in atoms))
    review = '此段缺少可用的短句邊界，請人工分段確認。' if len(text.splitlines()) > 2 else ''
    return SourceCaption(spans=[Span(start=atoms[0].start, end=atoms[-1].end)], text=text,
                         atoms=atoms, review_reason=review)


def from_transcript(transcript):
    cues, pending = [], []
    def flush():
        if pending:
            cues.extend(cue_from_atoms(group) for group in group_atoms(pending))
            pending.clear()
    for segment in transcript.segments:
        usable = (segment.words and lexical(''.join(w.text for w in segment.words)) == lexical(segment.text))
        if usable:
            atoms = [Atom(start=max(segment.start, w.start), end=min(segment.end, w.end), text=converter().convert(unicodedata.normalize('NFC', w.text)))
                     for w in segment.words if w.text.strip() and min(segment.end, w.end) > max(segment.start, w.start)]
            if pending and atoms and atoms[0].start - pending[-1].end >= .45:
                flush()
            pending.extend(atoms)
        else:
            flush()
            text = wrap(traditional(segment.text))
            long = len(text.splitlines()) > 2 or segment.end - segment.start > 6
            cues.append(SourceCaption(spans=[Span(start=segment.start, end=segment.end)], text=text,
                review_reason='這段只有整句時間，無法準確自動分段；請補充詞語時間或手動確認分段。' if long else ''))
    flush()
    return cues
