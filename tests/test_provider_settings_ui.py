import json
import pytest
from streamlit.testing.v1 import AppTest
from core.ai.provider import GeminiProvider, AIError, DEFAULT_MODELS
from core.ai import provider as module
from ui.settings import Services
from tests.conftest import ROOT
from tests.test_provider_resilience import sdk, error
from tests.test_ui import by_label, select_topic, navigate


@pytest.fixture
def model_settings(monkeypatch):
    from ui import settings
    monkeypatch.setattr(settings.st, 'secrets', {})
    for key in ('GEMINI_MODELS', 'GEMINI_MODEL', 'GEMINI_MAX_RETRIES'):
        monkeypatch.delenv(key, raising=False)
    return settings


def test_default_model_config_and_legacy_primary(model_settings, monkeypatch):
    assert model_settings.configured_models() == DEFAULT_MODELS
    monkeypatch.setenv('GEMINI_MODEL', 'approved-legacy')
    assert model_settings.configured_models() == ('approved-legacy', *DEFAULT_MODELS[1:])


@pytest.mark.parametrize('value', ['approved-one,approved-two', '["approved-one", "approved-two"]'])
def test_environment_allowlist_is_complete_not_appended(model_settings, monkeypatch, value):
    monkeypatch.setenv('GEMINI_MODELS', value)
    assert model_settings.configured_models() == ('approved-one', 'approved-two')


def test_secrets_array_has_priority_and_zero_retries_preserved(model_settings, monkeypatch):
    monkeypatch.setenv('GEMINI_MODELS', 'not-used')
    monkeypatch.setattr(model_settings.st, 'secrets', {'GEMINI_MODELS': ['approved-only'], 'GEMINI_MAX_RETRIES': 0})
    ai = model_settings.ai_provider()
    assert ai.models == ('approved-only',) and ai.max_retries == 0


def test_empty_secrets_key_still_uses_environment(model_settings, monkeypatch):
    monkeypatch.setattr(model_settings.st, 'secrets', {'GEMINI_API_KEY': ''})
    monkeypatch.setenv('GEMINI_API_KEY', 'test-environment-key')
    assert model_settings.ai_provider().api_key == 'test-environment-key'


@pytest.mark.parametrize('settings', [{'GEMINI_MODELS': []}, {'GEMINI_MODELS': '[invalid'}, {'GEMINI_MAX_RETRIES': 8}])
def test_bad_settings_show_safe_actionable_error(model_settings, monkeypatch, settings):
    monkeypatch.setattr(model_settings.st, 'secrets', settings)
    with pytest.raises(AIError, match='模型清單或重試參數設定無效'):
        model_settings.ai_provider()


def title_response():
    return json.dumps(dict(status='可延伸', reason='可從具體生活需求切入。', alternatives=[],
        titles=[dict(title='先整理每天的使用需求', topic='從生活習慣盤點空間需求。')]), ensure_ascii=False)


def test_ui_fallback_retains_context_shows_model_and_does_not_duplicate(monkeypatch, repo, catalog, sdk):
    from ui import settings
    ai = GeminiProvider('private-key', max_retries=0)
    monkeypatch.setattr(settings, 'services', lambda: Services(catalog, repo, ai, {}))
    sdk.outcomes = [error(503), title_response()]
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
    select_topic(at)
    by_label(at.button, '生成標題').click().run()
    assert not at.exception and len(sdk.calls) == 2
    assert any(DEFAULT_MODELS[1] in caption.value for caption in at.caption)
    at.run()
    assert len(sdk.calls) == 2
    by_label(at.button, '採用標題').click().run()
    navigate(at, '腳本編輯')
    sdk.outcomes = [error(503), json.dumps(dict(opening='開頭', body='已確認主體', ending='結尾'))]
    by_label(at.button, '生成逐字稿').click().run()
    original = at.session_state.draft.script
    selected = dict(at.session_state.draft.selection)
    sdk.outcomes = [error(503), json.dumps(dict(script='新版開頭\n\n已確認主體\n\n結尾', explanation='只改開頭'))]
    at.chat_input[0].set_value('只修改開頭，保留主體').run()
    assert at.session_state.draft.script == original
    assert at.session_state.draft.pending and len(at.session_state.draft.history) == 1
    assert at.session_state.draft.selection == selected
    payloads = [json.loads(c['contents']) for c in sdk.calls[-2:]]
    assert payloads[0] == payloads[1]
    assert payloads[-1]['request'] == '只修改開頭，保留主體'
    assert payloads[-1]['current_script'] == original
    by_label(at.button, '確認套用修改').click().run()
    by_label(at.button, '儲存腳本').click().run()
    at.run()
    assert len(sdk.calls) == 6
    assert len(repo.list_projects()) == 1
    assert len(repo.list_projects()[0].versions) == 2


def test_ui_all_models_fail_does_not_touch_draft(monkeypatch, repo, catalog, sdk):
    from ui import settings
    ai = GeminiProvider('private-key', max_retries=0)
    monkeypatch.setattr(settings, 'services', lambda: Services(catalog, repo, ai, {}))
    sdk.outcomes = [title_response()]
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
    select_topic(at)
    by_label(at.button, '生成標題').click().run()
    before = at.session_state.draft.model_dump_json()
    sdk.outcomes = [error(503)] * 3
    by_label(at.button, '重新生成標題').click().run()
    assert not at.exception and any('全部允許' in e.value for e in at.error)
    assert at.session_state.draft.model_dump_json() == before
    at.run()
    assert len(sdk.calls) == 4 and not repo.list_projects()


def test_rotating_audit_file_is_idempotent_and_excludes_content(tmp_path, sdk):
    logger = module.LOGGER
    original_handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    path = tmp_path / 'logs/calls.jsonl'
    try:
        module.configure_call_logging(path)
        module.configure_call_logging(path)
        assert len(logger.handlers) == len(original_handlers) + 1
        sdk.outcomes = [title_response()]
        from core.ai.title_generator import TitleResult
        GeminiProvider('private-key').generate('private-prompt', {'script': 'private-script'}, TitleResult)
        for handler in logger.handlers:
            handler.flush()
        content = path.read_text(encoding='utf-8')
        entry = json.loads(content)
        assert entry['outcome'] == 'success' and entry['model'] == DEFAULT_MODELS[0]
        for secret in ('private-key', 'private-prompt', 'private-script', '具體生活需求'):
            assert secret not in content
    finally:
        for handler in list(logger.handlers):
            if handler not in original_handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.setLevel(level)
        logger.propagate = propagate
