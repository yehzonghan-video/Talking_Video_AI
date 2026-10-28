import hashlib
import json
from core.subtitles.schemas import SubtitleTrack, SourceCaption, CaptionStyle, OutputCaption
from core.subtitles.segmentation import from_transcript, traditional, cue_from_atoms, group_atoms
from core.subtitles.mapping import map_captions, output_to_source, validate_output, time_map
from core.video.errors import VideoError


def transcript_signature(transcript):
    return hashlib.sha256(transcript.model_dump_json().encode()).hexdigest()


def generate(project, manager, replace=False, transcript=None):
    if project.subtitles is not None and not replace:
        return project  # No accidental resegmentation or loss of corrections.
    transcript = transcript or project.transcript
    if not transcript or not transcript.segments or transcript.timing != 'acoustic-alignment':
        raise VideoError('請先完成影片語音辨識，才能由實際口播產生字幕。')
    updated = project.model_copy(deep=True)
    old = updated.subtitles
    updated.subtitles = SubtitleTrack(cues=from_transcript(transcript), source_signature=transcript_signature(transcript),
        revision=old.revision + 1 if old else 1, style=old.style if old else CaptionStyle(),
        enabled=old.enabled if old else True, note='沿用聲學辨識；字幕未呼叫 Gemini。')
    return manager.save(updated)


def save_edits(project, manager, rows, style, enabled):
    if project.subtitles is None:
        raise VideoError('請先產生字幕。')
    timeline = project.timelines[-1]
    current = {c.id: c for c in map_captions(project.subtitles, timeline)}
    source_by_id = {c.id: c for c in project.subtitles.cues}
    outputs, sources, retained = [], [], {}
    for row in rows:
        text = traditional(str(row.get('text') or '')).replace('\r', '')
        highlights = row.get('highlights') or []
        if isinstance(highlights, str):
            highlights = [traditional(h) for h in highlights.split('｜') if h.strip()]
        if any(h not in text.replace('\n', '') for h in highlights):
            raise VideoError('黃色重點必須是該段字幕中已有的文字。')
        try:
            start, end = float(row['start']), float(row['end'])
        except (KeyError, ValueError, TypeError):
            raise VideoError('請填入每段字幕的開始與結束秒數。') from None
        row_id = row.get('id') if isinstance(row.get('id'), str) else ''
        old = current.get(row_id)
        confirmed = bool(row.get('confirmed', False))
        if old and old.needs_review and not confirmed:
            raise VideoError('請先確認標示待確認的字幕，修正後勾選「已確認」。')
        spans = output_to_source(start, end, timeline)
        out = OutputCaption(id=row_id, start=start, end=end, text=text, highlights=highlights, source_spans=spans)
        outputs.append(out)
        unchanged = old and (start, end, text) == (old.start, old.end, old.text) and not old.needs_review
        base_id = old.id.split(':')[0] if old else ''
        if unchanged and base_id in source_by_id and not source_by_id[base_id].manual:
            retained[old.id] = highlights
        else:
            sources.append(SourceCaption(spans=spans, text=text, highlights=highlights, manual=True))
    for original in project.subtitles.cues:
        fragments = [c for c in current.values() if c.id.split(':')[0] == original.id]
        if not fragments:
            sources.append(original.model_copy(deep=True))  # Currently cut away; keep for restore.
        elif not original.manual and all(c.id in retained for c in fragments):
            clone = original.model_copy(deep=True)
            clone.highlights = list(dict.fromkeys(h for c in fragments for h in retained[c.id]))
            sources.append(clone)
        elif original.atoms and not original.manual:
            # Keep unchanged visible fragments and hidden acoustic words separately;
            # never reinsert a deleted/edited visible fragment through another row.
            for fragment in fragments:
                if fragment.id in retained:
                    atoms = [a for a in original.atoms if any(a.start >= s.start - .00001 and a.end <= s.end + .00001 for s in fragment.source_spans)]
                    if atoms:
                        clone = cue_from_atoms(atoms)
                        clone.highlights = retained[fragment.id]
                        sources.append(clone)
            hidden = [a for a in original.atoms if not any(min(a.end, s.end) > max(a.start, s.start)
                       for c in fragments for s in c.source_spans)]
            sources.extend(cue_from_atoms(group) for group in group_atoms(hidden))
    sources.sort(key=lambda c: c.spans[0].start)
    validate_output(outputs, time_map(timeline)[-1].output_end)
    updated = project.model_copy(deep=True)
    updated.subtitles.cues = sources
    updated.subtitles.style = CaptionStyle.model_validate(style)
    updated.subtitles.enabled = enabled
    updated.subtitles.revision += 1
    return manager.save(updated)


def delivery_cues(project):
    if not project.subtitles:
        return []
    cues = map_captions(project.subtitles, project.timelines[-1])
    validate_output(cues, time_map(project.timelines[-1])[-1].output_end, require_reviewed=True)
    return cues


def save_preferences(project, manager, *, enabled):
    updated = project.model_copy(deep=True)
    updated.subtitles.enabled = enabled
    updated.subtitles.revision += 1
    return manager.save(updated)


def delivery_signature(project, *, include_disabled=False):
    track = project.subtitles
    payload = {'timeline': project.timelines[-1].model_dump(),
               'subtitles': track.model_dump() if track and (track.enabled or include_disabled) else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
