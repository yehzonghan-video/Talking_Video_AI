import copy
import json
from uuid import uuid4
import pytest
from pydantic import ValidationError
from core.subtitles.schemas import SourceCaption, Span
from core.subtitles.correction import analyze_cue, variant
from core.subtitles.service import generate, delivery_cues
from core.editor.service import document, save_document
from core.storage.project_manager import StorageError
from core.video.errors import VideoError
from core.video.export_service import export_mp4, export_srt
from tests.test_subtitles import caption_project
from tests.test_video_media import media_files


def cue(text):
    return SourceCaption(id='source-test', spans=[Span(start=0, end=5)], text=text)


def request(project):
    doc = document(project)
    return dict(protocol=1, operation_id=str(uuid4()), base_revision=doc['base_revision'], source_sha256=doc['source_sha256'],
        captions=[dict(id=c['id'], spans=c['spans'], text=c['text'], highlights=c['highlights'], confirmed=not c['review_reason']) for c in doc['sources']],
        cuts=[{k: c[k] for k in ('id', 'start', 'end', 'selected', 'confirmed')} for c in doc['cuts']],
        corrections=[dict(id=c['id'], decision=c['decision']) for c in doc['corrections']], style=doc['style'], enabled=doc['enabled'])


def test_context_supported_homophone_is_auto_but_raw_and_times_stay_unchanged():
    original = cue('這個空間我們做了三成收納設計。')
    before = original.model_dump_json()
    correction = analyze_cue(original, '這個空間我們做了三層收納設計。')
    assert correction.status == 'auto' and correction.decision == 'accepted'
    assert '三層' in correction.proposed
    corrected = variant(original, correction, 'accepted')
    assert corrected.spans == original.spans
    assert original.model_dump_json() == before
    assert variant(original, correction, 'rejected').text == original.text


@pytest.mark.parametrize('spoken,script', [
    ('這個空間我們做了室內色計。', '這個空間我們做了室內設計。'),
    ('這個空間我們做了兩層收納設計。', '這個空間我們做了三層收納設計。'),
    ('這個空間需要保留三十公分。', '這個空間需要保留三十公尺。'),
    ('這項裝潢的預算是30萬元。', '這項裝潢的預算是50萬元。'),
    ('我們預計在2026年10月施工。', '我們預計在2026年11月施工。'),
])
def test_near_sounds_and_important_facts_are_suggestions_only(spoken, script):
    correction = analyze_cue(cue(spoken), script)
    assert correction.status == 'review' and correction.decision == 'pending'
    assert variant(cue(spoken), correction, 'pending').text == spoken


def test_paraphrase_and_missing_script_sentences_are_never_inserted():
    original = cue('今天先聊一聊回家後放包包的位置。')
    correction = analyze_cue(original, '這個空間我們做了三層收納設計。\n總價五十萬元。')
    assert correction.status == 'keep' and correction.proposed == original.text


def test_short_ambiguous_homophone_is_not_auto_corrected():
    assert analyze_cue(cue('三成收納'), '三層收納').status == 'review'


def test_atomic_save_idempotency_and_no_unnecessary_timeline_version(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    before = project.transcript.model_dump_json()
    payload = request(project)
    payload['captions'][0]['text'] = '先確認生活需求。'
    saved = save_document(project.id, manager, payload)
    assert saved.subtitles.cues[0].manual and '生活需求' in saved.subtitles.cues[0].text
    assert len(saved.timelines) == len(project.timelines)
    assert saved.transcript.model_dump_json() == before
    assert save_document(project.id, manager, payload).revision == saved.revision
    assert manager.get(project.id).revision == saved.revision
    payload['captions'][0]['text'] = '不能重用識別碼覆寫'
    with pytest.raises(VideoError, match='識別碼'):
        save_document(project.id, manager, payload)


def test_manual_text_remains_after_regeneration_and_correction_refresh(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    payload = request(project)
    payload['captions'][0]['text'] = '人工確認的字幕內容。'
    project = save_document(project.id, manager, payload)
    regenerated = generate(project, manager, replace=True)
    assert any(c.text == '人工確認的字幕內容。' and c.manual for c in regenerated.subtitles.cues)


def test_cut_then_cancel_uses_original_acoustics_and_remaps_subtitles(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    original = project.transcript.model_dump_json()
    payload = request(project)
    payload['cuts'].append(dict(id=str(uuid4()), start=1.6, end=3.6, selected=True, confirmed=True))
    saved = save_document(project.id, manager, payload)
    assert delivery_cues(saved)[-1].start == pytest.approx(2)
    assert saved.transcript.model_dump_json() == original
    undo = request(saved)
    undo['cuts'][0].update(selected=False, confirmed=False)
    restored = save_document(saved.id, manager, undo)
    assert delivery_cues(restored)[-1].start == 4
    assert len(restored.timelines) == 3


@pytest.mark.parametrize('mutation', ['negative', 'nan', 'oversized', 'overlap', 'extra_path', 'false_confirmation', 'duplicate_id'])
def test_untrusted_frontend_data_rejected_without_partial_write(caption_project, mutation):
    project, manager, _ = caption_project
    project = generate(project, manager)
    payload = request(project)
    if mutation == 'negative': payload['captions'][0]['spans'][0]['start'] = -1
    if mutation == 'nan': payload['captions'][0]['spans'][0]['end'] = float('nan')
    if mutation == 'oversized': payload['captions'][0]['spans'][0]['end'] = 999
    if mutation == 'overlap': payload['captions'][1]['spans'][0]['start'] = .2
    if mutation == 'extra_path': payload['output_path'] = 'C:/arbitrary.mp4'
    if mutation == 'false_confirmation': payload['captions'][0]['confirmed'] = 'false'
    if mutation == 'duplicate_id': payload['captions'][1]['id'] = payload['captions'][0]['id']
    before = manager.get(project.id).model_dump_json()
    with pytest.raises((ValidationError, VideoError)):
        save_document(project.id, manager, payload)
    assert manager.get(project.id).model_dump_json() == before


def test_stale_browser_version_is_rejected_and_newer_edits_preserved(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    stale = request(project)
    new = request(project)
    new['captions'][0]['text'] = '另一個視窗已儲存的內容'
    saved = save_document(project.id, manager, new)
    with pytest.raises(StorageError, match='草稿'):
        save_document(project.id, manager, stale)
    assert manager.get(project.id).model_dump_json() == saved.model_dump_json()


def test_script_correction_choices_are_server_validated(caption_project):
    project, manager, _ = caption_project
    project = generate(project, manager)
    payload = request(project)
    payload['corrections'].append(dict(id='untrusted-correction', decision='accepted'))
    with pytest.raises(VideoError, match='校正'):
        save_document(project.id, manager, payload)


def test_manual_cut_can_override_default_without_confirmation_gate(caption_project):
    project, manager, _ = caption_project
    payload = request(generate(project, manager))
    payload['cuts'].append(dict(id='manual', start=2, end=3, selected=True, confirmed=False))
    saved = save_document(project.id, manager, payload)
    assert any(item.id == 'manual' and item.selected for item in saved.timelines[-1].decisions)


def test_editor_export_uses_saved_content_and_is_reused(caption_project, monkeypatch):
    project, manager, assets = caption_project
    project = generate(project, manager)
    project = save_document(project.id, manager, request(project))
    from core.video import export_service
    calls = []
    def render(source, output, timeline, media, expected_sha, **kwargs):
        calls.append(kwargs)
        output.write_bytes(b'validated-render-test')
    monkeypatch.setattr(export_service, 'render', render)
    result = export_mp4(project, manager, assets)
    assert len(calls) == 1 and calls[0]['subtitles']
    assert export_mp4(result, manager, assets).revision == result.revision
    assert len(calls) == 1
    result = save_document(result.id, manager, request(result))
    assert export_mp4(result, manager, assets).revision == result.revision
    assert len(calls) == 1
    assert '確認需求' in export_srt(result)
    result.subtitles.enabled = False
    result = manager.save(result)
    export_mp4(result, manager, assets)
    assert len(calls) == 2 and calls[-1] == {}


def test_media_reference_reads_once_across_reruns_then_recovers_eviction(tmp_path, monkeypatch):
    from ui import media_reference as media
    from types import SimpleNamespace
    from threading import RLock
    path = tmp_path / 'source.mp4'
    path.write_bytes(b'large-original-placeholder')
    reads = []
    class Manager:
        _lock = RLock()
        _file_metadata = {}
        _files_by_session_and_coord = {'session': {}}
        def add(self, filename, mime, coordinate):
            reads.append(Path(filename).read_bytes())
            self._file_metadata['media-id'] = True
            return '/media/media-id.mp4'
    from pathlib import Path
    manager = Manager()
    monkeypatch.setattr(media.runtime, 'exists', lambda: True)
    monkeypatch.setattr(media.runtime, 'get_instance', lambda: SimpleNamespace(media_file_mgr=manager))
    monkeypatch.setattr(media, 'get_script_run_ctx', lambda: SimpleNamespace(session_id='session'))
    monkeypatch.setattr(media.st, 'session_state', {})
    for _ in range(20):
        manager._files_by_session_and_coord['session'].clear()
        assert media.video_reference(path, 'project') == '/media/media-id.mp4'
    assert len(reads) == 1
    manager._file_metadata.clear()
    media.video_reference(path, 'project')
    assert len(reads) == 2


def test_explicit_confirmation_can_override_silence_speech_boundary(caption_project):
    from core.video.schemas import Decision
    project, manager, _ = caption_project
    project.suggestions = [Decision(id='silence-edge', start=1.6, end=2.0, kind='silence', reason='邊界建議', requires_review=False)]
    project = generate(manager.save(project), manager)
    payload = request(project)
    payload['cuts'][0].update(selected=True, confirmed=True)
    saved = save_document(project.id, manager, payload)
    assert saved.timelines[-1].decisions[0].requires_review
    assert saved.timelines[-1].decisions[0].confirmed
