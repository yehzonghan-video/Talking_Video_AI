"""Authoritative script text aligned to retained acoustic anchors, without AI.

No characters are timed by an evenly spaced synthetic clock. Substitutions
inherit the surrounding real word/segment intervals; missing sentences remain
unaligned rather than being inserted into the video.
"""
from difflib import SequenceMatcher
from hashlib import sha256
import re
from uuid import uuid5, NAMESPACE_URL
from core.subtitles.schemas import SourceCaption, Span, Atom
from core.subtitles.segmentation import lexical, wrap, tokens, width


def script_signature(script):
    return sha256(script.encode('utf-8')).hexdigest()


def sentences(script):
    return [s for s in re.findall(r'[^。！？!?\n]+[。！？!?]?|\n+', script) if s.strip()]


def align_script(script, transcript, timeline):
    acoustic, anchors = '', []
    for segment in transcript.segments:
        words = segment.words if segment.words and lexical(''.join(w.text for w in segment.words)) == lexical(segment.text) else [segment]
        for word in words:
            # Exclude deleted retakes before matching; never align to a removed
            # first take when the final take is the one that will be heard.
            if not any(word.start >= k.start - .001 and word.end <= k.end + .001 for k in timeline.keep_segments):
                continue
            text = lexical(word.text)
            acoustic += text
            anchors.extend([(word.start, word.end, not bool(segment.words))] * len(text))
    units = sentences(script)
    normalized = [lexical(s) for s in units]
    target = ''.join(normalized)
    matches = {}
    for block in SequenceMatcher(None, target, acoustic, autojunk=False).get_matching_blocks():
        for offset in range(block.size):
            matches[block.a + offset] = block.b + offset
    cues, missing, cursor = [], [], 0
    occupied_until = -1.0
    for index, (text, clean) in enumerate(zip(units, normalized)):
        found = [(i, matches[cursor + i]) for i in range(len(clean)) if cursor + i in matches]
        cursor += len(clean)
        if not clean:
            continue
        # Long absent sentences often share generic words. Require substantial
        # lexical coverage and a plausible contiguous acoustic sequence.
        if (len(found) / len(clean) < .65 or not found or
                SequenceMatcher(None, clean, acoustic[found[0][1]:found[-1][1] + 1], autojunk=False).ratio() < .65):
            missing.append(text)
            continue
        start, end = anchors[found[0][1]][0], anchors[found[-1][1]][1]
        if start < occupied_until - .001:
            # Segment-only timestamps cannot locate distinct script lines
            # within one segment. Never invent a uniform character clock.
            missing.append(text)
            continue
        reason = '文字以逐字稿為準，使用整句聲學邊界對齊。' if any(anchors[j][2] for _, j in found) else ''
        # Keep the exact script punctuation. Wrap only for display, never
        # tokenize the ASR text into subtitle sentences.
        # Split long script sentences only at token boundaries with distinct
        # measured word times. With segment-only times keep one measured cue.
        chunks, current, local = [], '', 0
        for token in tokens(text):
            current += token
            local += len(lexical(token))
            before = [j for i, j in found if i < local]
            after = [j for i, j in found if i >= local]
            boundary = (before and after and anchors[before[-1]][1] <= anchors[after[0]][0] + .001)
            if boundary and (width(current) >= 24 or width(current) >= 12 and re.search(r'[，；：,;:]$', current)):
                chunks.append((current, local))
                current = ''
        if current:
            chunks.append((current, len(clean)))
        offset = 0
        for part, (chunk, stop) in enumerate(chunks):
            begin = offset
            located = [j for i, j in found if offset <= i < stop]
            offset = stop
            if not located:
                missing.append(chunk)
                continue
            atoms = []
            if not reason:
                position = begin
                for char in chunk:
                    prior = [(i, j) for i, j in found if begin <= i <= position and i < stop]
                    following = [(i, j) for i, j in found if position <= i < stop]
                    j = prior[-1][1] if prior else following[0][1] if following else located[-1]
                    a, b, _ = anchors[j]
                    if atoms and atoms[-1].start == a and atoms[-1].end == b:
                        atoms[-1].text += char
                    else:
                        atoms.append(Atom(start=a, end=b, text=char))
                    position += len(lexical(char))
            cues.append(SourceCaption(id=str(uuid5(NAMESPACE_URL, script_signature(script) + f'{index}:{part}')),
                spans=[Span(start=anchors[located[0]][0], end=anchors[located[-1]][1])],
                text=wrap(chunk), atoms=atoms, review_reason=reason))
        occupied_until = end
    return cues, missing
