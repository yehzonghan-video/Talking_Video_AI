import json
import wave
import pytest
from core.ai import provider as module
from core.ai.diagnostics import api_diagnostic
from core.ai.provider import GeminiProvider, AIError, classify
from core.editing.edit_planner import SemanticPlan, semantic_plan
from core.video.schemas import Transcript, Segment, Decision
from core.video.assets import LocalAssets, sha256
from core.video.project_manager import VideoProjectManager
from core.video.uploader import create_project
from core.video.service import analyze, confirm_timeline
from core.workflow import project_from_draft
from tests.test_provider_resilience import sdk, error
from tests.test_video_media import media_files


def transcript():
    return Transcript(provider='test', model='mock-acoustic', timing='acoustic-alignment', segments=[
        Segment(id='seg_0001', start=.1, end=1.5, text='先確認需求。'),
        Segment(id='seg_0002', start=4, end=6.8, text='先確認需求，再安排預算。')])


def has_array_bounds(value):
    if isinstance(value, dict):
        return bool({'maxItems', 'minItems'} & value.keys()) or any(has_array_bounds(v) for v in value.values())
    return isinstance(value, list) and any(has_array_bounds(v) for v in value)


def test_semantic_wire_schema_is_small_but_local_limits_are_preserved(sdk):
    original = SemanticPlan.model_json_schema()
    sdk.outcomes = ['{"suggestions":[],"matches":[]}']
    semantic_plan(GeminiProvider('private-key'), '先確認需求。', transcript(), 8, .15)
    call = sdk.calls[0]
    assert not has_array_bounds(call['config'].response_json_schema)
    assert has_array_bounds(original) and SemanticPlan.model_json_schema() == original
    assert call['config'].response_mime_type == 'application/json'
    payload = json.loads(call['contents'])
    assert set(payload) == {'script_sentences', 'segments'}
    assert all(set(s) == {'id', 'text'} for s in payload['segments'])
    # The transport carries text only: no audio bytes, MIME parts or guessed times.
    assert isinstance(call['contents'], str)
    assert 'inline_data' not in call['contents'] and 'file_uri' not in call['contents']


@pytest.mark.parametrize('value', [
    {'suggestions': [{'segment_ids': ['seg_0001'], 'reason': 'test', 'kind': 'retake'}] * 151, 'matches': []},
    {'suggestions': [], 'matches': [{'script_index': 0, 'segment_ids': [], 'status': 'missing', 'reason': 'test'}] * 301},
    {'suggestions': [{'segment_ids': [], 'reason': 'test', 'kind': 'retake'}], 'matches': []},
    {'suggestions': [{'segment_ids': ['seg_0001'] * 31, 'reason': 'test', 'kind': 'retake'}], 'matches': []},
])
def test_simplified_wire_schema_still_rejects_invalid_output(sdk, value):
    sdk.outcomes = [json.dumps(value)]
    with pytest.raises(AIError, match='格式'):
        GeminiProvider('key', models=['approved']).generate('test', {}, SemanticPlan)


@pytest.mark.parametrize('message,kind,cause', [
    ('Schema produces a constraint with too many states for serving', 'invalid_schema', 'schema_complexity'),
    ('generation_config.response_json_schema has an invalid property', 'invalid_schema', 'invalid_schema'),
    ('Model does not support response_mime_type application/json', 'model_unsupported', 'model_unsupported'),
    ('Unsupported audio MIME type audio/invalid', 'invalid_audio', 'invalid_audio'),
    ('Invalid value at generation_config.temperature', 'invalid_parameter', 'invalid_parameter'),
    ('Request payload size exceeds limit', 'request_too_large', 'request_too_large'),
    ('Request contains an invalid argument.', 'invalid_request', 'invalid_request'),
])
def test_400_is_classified_and_never_retried(sdk, message, kind, cause):
    exc = error(400, message=message)
    assert classify(exc).kind == kind
    assert api_diagnostic(exc)['cause'] == cause
    sdk.outcomes = [exc]
    with pytest.raises(AIError, match='診斷編號'):
        GeminiProvider('private-key').generate('test', {}, SemanticPlan)
    assert len(sdk.calls) == 1


def test_cloud_console_and_file_diagnostics_redact_all_untrusted_text(tmp_path, sdk, capsys):
    logger = module.LOGGER
    original_handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    path = tmp_path / 'safe.jsonl'
    try:
        module.configure_call_logging(path)
        sdk.outcomes = [error(400, message='Invalid value at generation_config.response_json_schema: '
                              'private-key secret-transcript secret-prompt https://example.com?key=secret', details=[{
            '@type': 'type.googleapis.com/google.rpc.BadRequest', 'fieldViolations': [{
                'field': 'generation_config.response_json_schema', 'description': 'secret-transcript'}]}])]
        with pytest.raises(AIError) as raised:
            GeminiProvider('private-key').generate('secret-prompt', {'script': 'secret-transcript'}, SemanticPlan)
        for handler in logger.handlers:
            handler.flush()
        text = path.read_text(encoding='utf-8')
        entry = json.loads(text)
        assert entry['error_type'] == 'invalid_schema'
        assert entry['diagnostic']['fields'] == ['response_json_schema', 'generation_config']
        assert entry['request']['operation'] == 'video_semantic_alignment'
        assert entry['request']['media_parts'] == 0 and entry['request']['input_bytes'] > 0
        assert entry['request_id'] in str(raised.value)
        captured = capsys.readouterr().err
        assert entry['request_id'] in captured
        for sensitive in ('private-key', 'secret-transcript', 'secret-prompt', 'example.com'):
            assert sensitive not in text + captured + str(raised.value)
    finally:
        for handler in list(logger.handlers):
            if handler not in original_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(level)
        logger.propagate = propagate


def test_real_sdk_serializes_semantic_schema_as_json_text_only(monkeypatch):
    import httpx
    from google import genai
    actual_client = genai.Client
    requests = []
    def respond(request):
        assert request.headers['content-type'].startswith('application/json')
        body = json.loads(request.content)
        requests.append(body)
        assert set(body['contents'][0]['parts'][0]) == {'text'}
        assert not has_array_bounds(body['generationConfig']['responseJsonSchema'])
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{"suggestions":[],"matches":[]}'}]}}]})
    def client(**kwargs):
        kwargs['http_options'].httpx_client = httpx.Client(transport=httpx.MockTransport(respond))
        return actual_client(**kwargs)
    monkeypatch.setattr(genai, 'Client', client)
    semantic_plan(GeminiProvider('test-key'), '先確認需求。', transcript(), 8, .15)
    assert len(requests) == 1


def test_400_preserves_original_pcm_asr_local_analysis_and_confirmed_edits(media_files, tmp_path, draft, catalog, sdk):
    assets, manager = LocalAssets(tmp_path / 'media'), VideoProjectManager(tmp_path / 'project.db')
    script = project_from_draft(draft, catalog.combo_id(draft.selection))
    with media_files['mp4'].open('rb') as upload:
        project = create_project(script, upload, 'source.mp4', assets, manager)
    project = confirm_timeline(project, manager, [Decision(start=2, end=3, kind='manual',
        reason='已人工確認', selected=True, confirmed=True)])
    project.output_key, project.output_timeline, project.export_status = 'saved-output.mp4', 2, '已輸出'
    assets.path(project.id, project.output_key).write_bytes(b'previous-output')
    project = manager.save(project)
    timelines = [t.model_dump() for t in project.timelines]
    class ASR:
        model_name = 'mock-acoustic'
        calls = 0
        def transcribe(self, audio, duration, progress):
            self.calls += 1
            with wave.open(str(audio), 'rb') as pcm:
                assert (pcm.getframerate(), pcm.getnchannels(), pcm.getsampwidth()) == (16000, 1, 2)
            assert 0 < audio.stat().st_size < 300_000
            return transcript()
    asr = ASR()
    sdk.outcomes = [error(400, message='Response schema has too many states')]
    failed = analyze(project, manager, assets, asr, GeminiProvider('test-key'))
    saved = manager.get(project.id)
    assert 'AI 文字語意比對未完成' in saved.analysis_note and '診斷編號' in saved.analysis_note
    assert saved.transcript and saved.silences and saved.suggestions and saved.matches
    assert [t.model_dump() for t in saved.timelines] == timelines
    assert saved.output_key == 'saved-output.mp4' and assets.path(saved.id, saved.output_key).read_bytes() == b'previous-output'
    assert sha256(assets.source(saved)) == project.source_sha256
    assert not saved.analysis_signature and not list(assets.project_dir(saved.id).glob('temp-audio-*.wav'))
    sdk.outcomes = ['{"suggestions":[],"matches":[]}']
    done = analyze(failed, manager, assets, asr, GeminiProvider('test-key'))
    assert asr.calls == 1 and done.analysis_signature and len(sdk.calls) == 2
    assert [t.model_dump() for t in done.timelines] == timelines
