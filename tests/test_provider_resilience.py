import copy
import json
import logging
from pathlib import Path
from types import SimpleNamespace
import pytest
from pydantic import BaseModel, ConfigDict
from google.genai import errors
from core.ai import provider as module
from core.ai.provider import GeminiProvider, AIError, DEFAULT_MODELS, classify, model_list
from core.ai.conversation import revise, RevisionResult


class Reply(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str


def error(code, *, details=None, message='private-request-and-key', header=None):
    payload = {'error': {'code': code, 'message': message, 'details': details or []}}
    cls = errors.ServerError if code >= 500 else errors.ClientError
    response = SimpleNamespace(headers={'Retry-After': header} if header is not None else {})
    return cls(code, payload, response=response)


def minute_error(delay=None):
    details = [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [
        {'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}]
    if delay is not None:
        details.append({'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': f'{delay}s'})
    return error(429, details=details)


def daily_error():
    return error(429, details=[{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [
        {'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
         'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]},
        {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '1s'}])


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = 0.0
        sleeps = []
        def sleep(self, delay):
            self.sleeps.append(delay)
            self.now += delay
    clock = Clock()
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock.now)
    monkeypatch.setattr(module.time, 'sleep', clock.sleep)
    monkeypatch.setattr(module.random, 'uniform', lambda *args: 0)
    return clock


@pytest.fixture
def sdk(monkeypatch):
    from google import genai
    state = SimpleNamespace(outcomes=[], calls=[], clients=[])
    class Client:
        def __init__(self, **kwargs):
            state.clients.append(kwargs)
            self.models = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def generate_content(self, **kwargs):
            state.calls.append(copy.deepcopy(kwargs))
            if not state.outcomes:
                raise AssertionError('Unexpected duplicate or unauthorized request')
            outcome = state.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if callable(outcome):
                outcome = outcome(kwargs)
            return SimpleNamespace(text=outcome)
    monkeypatch.setattr(genai, 'Client', Client)
    return state


def test_default_authorized_order_and_explicit_allowlist():
    assert GeminiProvider('key').models == DEFAULT_MODELS
    assert model_list(' ["models/first", "first", "second"] ') == ('first', 'second')
    assert GeminiProvider('key', models=['only-approved']).models == ('only-approved',)


@pytest.mark.parametrize('models', [[], [''], ['a', 3], ['https://example.com'], [str(i) for i in range(6)]])
def test_invalid_allowlist_rejected(models):
    with pytest.raises(ValueError): GeminiProvider('key', models=models)


@pytest.mark.parametrize('kwargs', [dict(max_retries=4), dict(max_retries=-1), dict(max_retries=True),
    dict(initial_delay=0), dict(max_delay=31), dict(max_elapsed=float('inf')), dict(request_timeout=61)])
def test_retry_settings_are_bounded(kwargs):
    with pytest.raises(ValueError): GeminiProvider('key', **kwargs)


def test_primary_success_no_extra_call_and_validated_metadata(sdk, clock):
    sdk.outcomes = ['{"text":"ok"}']
    ai = GeminiProvider('private-key')
    assert ai.generate('instruction', {'abc': 'A01-B01-C03'}, Reply).text == 'ok'
    assert ai.last_model == DEFAULT_MODELS[0]
    assert len(sdk.calls) == 1 and not clock.sleeps
    assert sdk.clients[0]['http_options'].retry_options.attempts == 1
    assert sdk.calls[0]['config'].http_options.retry_options.attempts == 1


def test_503_backoff_then_first_fallback_preserves_context(sdk, clock):
    sdk.outcomes = [error(503)] * 3 + ['{"text":"ok"}']
    ai = GeminiProvider('private-key')
    payload = {'abc': {'a': 'A01', 'b': 'B01', 'c': 'C03'}, 'current_script': '使用者已確認的稿件', 'history': [{'request': '修改開頭'}]}
    before = copy.deepcopy(payload)
    result = ai.generate('保留指定段落', payload, Reply)
    assert result.text == 'ok' and ai.last_model == DEFAULT_MODELS[1]
    assert [c['model'] for c in sdk.calls] == [DEFAULT_MODELS[0]] * 3 + [DEFAULT_MODELS[1]]
    assert clock.sleeps == [1, 2]
    assert payload == before
    assert len({c['contents'] for c in sdk.calls}) == 1
    assert all(c['config'].system_instruction == '保留指定段落' for c in sdk.calls)
    assert all(c['config'].response_json_schema == Reply.model_json_schema() for c in sdk.calls)


def test_second_fallback_after_both_models_exhausted(sdk, clock):
    sdk.outcomes = [error(503)] * 6 + ['{"text":"ok"}']
    ai = GeminiProvider('private-key')
    ai.generate('test', {}, Reply)
    assert ai.last_model == DEFAULT_MODELS[2]
    assert len(sdk.calls) == 7 and clock.sleeps == [1, 2, 1, 2]


def test_all_models_fail_is_bounded_and_clear(sdk, clock):
    sdk.outcomes = [error(503)] * 9
    ai = GeminiProvider('private-key')
    with pytest.raises(AIError, match='全部允許') as caught:
        ai.generate('敏感Prompt', {'script': '敏感稿件'}, Reply)
    assert len(sdk.calls) == 9 and len(clock.sleeps) == 6
    assert ai.last_model is None
    assert 'private-key' not in str(caught.value) and '敏感' not in str(caught.value)


def test_daily_quota_takes_precedence_over_retry_info(sdk, clock):
    sdk.outcomes = [daily_error()]
    with pytest.raises(AIError, match='每日配額'):
        GeminiProvider('private-key').generate('test', {}, Reply)
    assert len(sdk.calls) == 1 and not clock.sleeps


def test_short_rate_limit_retries_same_model_then_succeeds(sdk, clock):
    sdk.outcomes = [minute_error(3), '{"text":"ok"}']
    ai = GeminiProvider('key')
    ai.generate('test', {}, Reply)
    assert ai.last_model == DEFAULT_MODELS[0]
    assert clock.sleeps == [3]
    assert len({c['model'] for c in sdk.calls}) == 1


def test_exhausted_rate_limit_does_not_cycle_models(sdk, clock):
    sdk.outcomes = [minute_error()] * 3
    with pytest.raises(AIError, match='短期速率限制'):
        GeminiProvider('key').generate('test', {}, Reply)
    assert len(sdk.calls) == 3 and len({c['model'] for c in sdk.calls}) == 1


def test_ambiguous_429_stops_without_guessing_or_switching(sdk, clock):
    sdk.outcomes = [error(429, message='You exceeded your current quota')]
    with pytest.raises(AIError, match='無法確認限制類型'):
        GeminiProvider('key').generate('test', {}, Reply)
    assert len(sdk.calls) == 1 and not clock.sleeps


@pytest.mark.parametrize('metric,kind', [
    ('GenerateRequestsPerMinutePerProjectPerModel', 'rate_limit'),
    ('GenerateRequestsPerDayPerProjectPerModel', 'daily_quota'),
    ('UnspecifiedQuota', 'unknown_quota'),
])
def test_generic_quota_exceeded_words_do_not_override_metric(metric, kind):
    exc = error(429, message='Quota exceeded for metric; check your current quota.', details=[
        {'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': metric}]}])
    assert classify(exc).kind == kind


def test_retry_after_header_is_respected_and_long_wait_stops(sdk, clock):
    sdk.outcomes = [error(429, header='4'), '{"text":"ok"}']
    GeminiProvider('key').generate('test', {}, Reply)
    assert clock.sleeps == [4]
    sdk.calls.clear()
    clock.sleeps.clear()
    sdk.outcomes = [minute_error(60)]
    with pytest.raises(AIError, match='等待的時間超過'):
        GeminiProvider('key').generate('test', {}, Reply)
    assert len(sdk.calls) == 1 and not clock.sleeps


@pytest.mark.parametrize('code', [400, 401, 402, 403])
def test_setup_permission_and_billing_errors_do_not_retry(sdk, clock, code):
    sdk.outcomes = [error(code)]
    with pytest.raises(AIError): GeminiProvider('key').generate('test', {}, Reply)
    assert len(sdk.calls) == 1 and not clock.sleeps


def test_unavailable_model_uses_only_next_approved_model(sdk, clock):
    sdk.outcomes = [error(404), '{"text":"ok"}']
    ai = GeminiProvider('key', models=['approved-one', 'approved-two'])
    ai.generate('test', {}, Reply)
    assert [c['model'] for c in sdk.calls] == ['approved-one', 'approved-two']
    assert not clock.sleeps


def test_invalid_fallback_is_not_accepted_and_next_model_is_validated(sdk, clock):
    sdk.outcomes = [error(503), 'broken-json', '{"text":"valid"}']
    ai = GeminiProvider('key', max_retries=0)
    assert ai.generate('test', {}, Reply).text == 'valid'
    assert ai.last_model == DEFAULT_MODELS[2] and len(sdk.calls) == 3


def test_all_invalid_schema_outputs_fail_without_success_metadata(sdk, clock):
    sdk.outcomes = ['{"wrong":"shape"}', 'broken-json', '']
    ai = GeminiProvider('key')
    with pytest.raises(AIError, match='格式'):
        ai.generate('test', {}, Reply)
    assert ai.last_model is None and len(sdk.calls) == 3 and not clock.sleeps


def test_dialogue_failover_sends_latest_request_and_all_history(sdk, clock):
    sdk.outcomes = [error(503), json.dumps({'script': '完整的新稿', 'explanation': '只修改開頭'})]
    ai = GeminiProvider('key', max_retries=0)
    history = [dict(request='上次請保留第二段', proposal='先前版本', outcome='已套用')]
    result = revise(ai, {'a': {'id': 'A01'}}, '既有標題', '目前已確認的全文', 45, history, '這次只改開頭', {})
    assert result.script == '完整的新稿'
    bodies = [json.loads(c['contents']) for c in sdk.calls]
    assert bodies[0] == bodies[1]
    assert bodies[1]['history'] == history
    assert bodies[1]['current_script'] == '目前已確認的全文'
    assert bodies[1]['request'] == '這次只改開頭'


def test_total_budget_limits_calls_and_request_timeout(sdk, clock):
    def slow_failure(kwargs):
        assert kwargs['config'].http_options.timeout == 1000
        clock.now += 1.1
        raise error(503)
    sdk.outcomes = [slow_failure]
    ai = GeminiProvider('key', max_elapsed=1)
    with pytest.raises(AIError, match='時間上限'):
        ai.generate('test', {}, Reply)
    assert len(sdk.calls) == 1 and not clock.sleeps


def test_success_metadata_cleared_on_later_failure(sdk, clock):
    ai = GeminiProvider('key', models=['approved'])
    sdk.outcomes = ['{"text":"ok"}']
    ai.generate('test', {}, Reply)
    sdk.outcomes = [error(401)]
    with pytest.raises(AIError): ai.generate('test', {}, Reply)
    assert ai.last_model is None


def test_audit_records_only_safe_metadata(sdk, clock):
    records = []
    class Capture(logging.Handler):
        def emit(self, record): records.append(json.loads(record.getMessage()))
    handler = Capture()
    old_level = module.LOGGER.level
    module.LOGGER.addHandler(handler)
    module.LOGGER.setLevel(logging.INFO)
    try:
        sdk.outcomes = [error(503), '{"text":"sensitive-output"}']
        ai = GeminiProvider('private-key', max_retries=0)
        ai.generate('sensitive-prompt', {'script': 'sensitive-script'}, Reply)
    finally:
        module.LOGGER.removeHandler(handler)
        module.LOGGER.setLevel(old_level)
    assert [r['outcome'] for r in records] == ['failure', 'success']
    assert records[0]['error_type'] == 'unavailable' and records[0]['http_status'] == 503
    assert all('elapsed_ms' in r and 'model' in r for r in records)
    serialized = json.dumps(records)
    for secret in ('private-key', 'sensitive-prompt', 'sensitive-script', 'sensitive-output', 'private-request'):
        assert secret not in serialized


def test_real_sdk_http_transport_has_no_hidden_retries(monkeypatch, clock):
    import httpx
    from google import genai
    actual_client = genai.Client
    requests = []
    def respond(request):
        requests.append(str(request.url))
        if len(requests) < 3:
            return httpx.Response(503, json={'error': {'code': 503, 'message': 'busy'}})
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{"text":"ok"}'}]}}]})
    def client(**kwargs):
        kwargs['http_options'].httpx_client = httpx.Client(transport=httpx.MockTransport(respond))
        return actual_client(**kwargs)
    monkeypatch.setattr(genai, 'Client', client)
    ai = GeminiProvider('test-only', max_retries=1)
    assert ai.generate('mock', {}, Reply).text == 'ok'
    assert len(requests) == 3
    assert ai.last_model == DEFAULT_MODELS[1]
