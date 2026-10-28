import hashlib
import json
from typing import Literal
from pydantic import Field, StrictBool
from core.storage.schemas import StrictModel, identifier
from core.subtitles.schemas import Span, SourceCaption, CaptionStyle
from core.subtitles.correction import prepare_track, variant
from core.subtitles.mapping import map_captions, validate_output, time_map
from core.subtitles.segmentation import traditional
from core.video.schemas import Decision
from core.video.timeline import build_timeline
from core.video.errors import VideoError
from core.storage.project_manager import StorageError


class CaptionEdit(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    spans: list[Span] = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    highlights: list[str] = Field(default_factory=list, max_length=30)
    confirmed: StrictBool = False


class CutEdit(Span):
    id: str = Field(min_length=1, max_length=100)
    selected: StrictBool
    confirmed: StrictBool = False


class CorrectionChoice(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    decision: Literal['accepted', 'rejected', 'pending']


class EditRequest(StrictModel):
    protocol: Literal[1]
    operation_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    base_revision: int = Field(ge=0, strict=True)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    captions: list[CaptionEdit] = Field(max_length=3000)
    cuts: list[CutEdit] = Field(max_length=300)
    corrections: list[CorrectionChoice] = Field(max_length=3000)
    style: CaptionStyle
    enabled: StrictBool


def decisions(project):
    by_id = {d.id: d.model_copy(deep=True) for d in project.suggestions}
    for item in by_id.values():
        item.selected = item.confirmed = False
    by_id.update({d.id: d.model_copy(deep=True) for d in project.timelines[-1].decisions})
    return list(by_id.values())


def document(project):
    track = prepare_track(project.subtitles, project.script_snapshot) if project.subtitles else None
    variants = {}
    if track:
        originals = {c.id: c for c in track.original_cues}
        for correction in track.corrections:
            if correction.cue_id in originals:
                variants[correction.id] = {choice: variant(originals[correction.cue_id], correction, choice).model_dump()
                                          for choice in ('accepted', 'rejected', 'pending')}
    return {'protocol': 1, 'project_id': project.id, 'base_revision': project.revision, 'source_sha256': project.source_sha256,
        'title': project.title, 'duration': project.media.duration,
        'video': {'width': project.media.display_width, 'height': project.media.display_height},
        'sources': [c.model_dump() for c in track.cues] if track else [],
        'corrections': [c.model_dump() for c in track.corrections] if track else [], 'variants': variants,
        'cuts': [c.model_dump() for c in decisions(project)],
        'style': track.style.model_dump() if track else CaptionStyle().model_dump(), 'enabled': track.enabled if track else False,
        'last_operation': project.editor_last_operation}


def save_document(project_id, manager, payload):
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 4_000_000:
        raise VideoError('編輯資料過大，請分次處理。')
    request = EditRequest.model_validate(payload)
    digest = hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True).encode()).hexdigest()
    project = manager.get(project_id)
    if project.editor_last_operation == request.operation_id:
        if project.editor_last_hash != digest:
            raise VideoError('儲存識別碼已被不同內容使用，請重新儲存。')
        return project  # Idempotent replay after a Streamlit rerun/reconnect.
    if project.revision != request.base_revision:
        raise StorageError('專案已由其他操作更新；瀏覽器草稿仍保留，請先下載草稿，再重新載入專案。')
    if project.source_sha256 != request.source_sha256:
        raise VideoError('影片來源已變更，請重新開啟正確專案。')
    updated = project.model_copy(deep=True)
    trusted = {d.id: d for d in decisions(project)}
    if len({c.id for c in request.cuts}) != len(request.cuts):
        raise VideoError('剪輯片段識別碼重複。')
    edits = []
    for item in request.cuts:
        if item.end > project.media.duration:
            raise VideoError('剪輯超出原片長度。')
        old = trusted.get(item.id)
        decision = old.model_copy(deep=True) if old else Decision(id=item.id, start=item.start, end=item.end, kind='manual', reason='視覺化編輯器人工剪輯')
        if (decision.start, decision.end) != (item.start, item.end):
            decision.requires_review = True
        decision.start, decision.end, decision.selected, decision.confirmed = item.start, item.end, item.selected, item.confirmed
        if item.selected and item.confirmed:
            decision.requires_review = True  # Explicit user choice, including a silence boundary override.
        edits.append(decision)
    if any(d.selected and d.id not in {c.id for c in request.cuts} for d in trusted.values()):
        raise VideoError('已確認的剪輯片段遺漏；請使用取消刪除操作保留內容。')
    old_timeline = project.timelines[-1]
    candidate = build_timeline(project.media.duration, edits, old_timeline.number + 1, '視覺化編輯器確認剪輯')
    prior_ids = {d.id for d in old_timeline.decisions}
    meaningful = [d for d in edits if d.selected or d.id in prior_ids]
    if [d.model_dump() for d in meaningful] != [d.model_dump() for d in old_timeline.decisions]:
        updated.timelines.append(candidate)
    if project.subtitles:
        track = prepare_track(project.subtitles, project.script_snapshot)
        originals = {c.id: c for c in track.original_cues}
        choices = {c.id: c.decision for c in request.corrections}
        if len(choices) != len(request.corrections) or set(choices) != {c.id for c in track.corrections}:
            raise VideoError('腳本校正資料已變更，請重新載入。')
        allowed = {c.id: c for c in track.cues}
        for correction in track.corrections:
            correction.decision = choices[correction.id]
            if correction.cue_id in originals:
                old = allowed.get(correction.cue_id)
                if old is None or not old.manual or old.correction_ref:
                    allowed[correction.cue_id] = variant(originals[correction.cue_id], correction, correction.decision)
        if len({c.id for c in request.captions}) != len(request.captions):
            raise VideoError('字幕識別碼重複。')
        sources = []
        for item in request.captions:
            text = item.text if track.text_source == 'script' else traditional(item.text)
            if any(s.end > project.media.duration for s in item.spans):
                raise VideoError('字幕時間超出原片。')
            if any(b.start < a.end for a, b in zip(item.spans, item.spans[1:])):
                raise VideoError('字幕來源時間不能重疊或倒置。')
            if any(not h or h not in text.replace('\n', '') for h in item.highlights):
                raise VideoError('黃色重點必須是字幕中已有的文字。')
            old = allowed.get(item.id)
            if old and (old.text, old.spans) == (text, item.spans):
                source = old.model_copy(deep=True)
                if source.review_reason and item.confirmed:
                    source.atoms, source.manual, source.review_reason, source.correction_ref = [], True, '', ''
                source.highlights = item.highlights
            else:
                source = SourceCaption(id=item.id, spans=item.spans, text=text, highlights=item.highlights, manual=True)
            sources.append(source)
        track.cues, track.style, track.enabled = sorted(sources, key=lambda c: c.spans[0].start), request.style, request.enabled
        # Saving an unchanged document must not invalidate a completed MP4.
        # The outer project revision still advances for optimistic locking.
        if track.model_dump(exclude={'revision'}) != project.subtitles.model_dump(exclude={'revision'}):
            track.revision += 1
        validate_output(map_captions(track, updated.timelines[-1]), time_map(updated.timelines[-1])[-1].output_end)
        updated.subtitles = track
    elif request.captions or request.corrections:
        raise VideoError('請先由聲學辨識產生字幕。')
    updated.editor_last_operation, updated.editor_last_hash = request.operation_id, digest
    return manager.save(updated)  # One validated optimistic transaction for cuts + captions.
