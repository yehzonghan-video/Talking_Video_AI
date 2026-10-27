import pytest
from streamlit.testing.v1 import AppTest
from core.ai.provider import GeminiProvider, DEFAULT_MODELS, AIError
from tests.test_provider_resilience import sdk, error
from tests.test_provider_settings_ui import title_response
from tests.conftest import ROOT
from tests.test_ui import by_label, select_topic
from ui.settings import Services


def test_manual_priority_and_reset_keep_administrator_order():
    ai = GeminiProvider('test-key')
    ai.prefer_model(DEFAULT_MODELS[2])
    assert ai.models == (DEFAULT_MODELS[2], DEFAULT_MODELS[0], DEFAULT_MODELS[1])
    ai.prefer_model(DEFAULT_MODELS[1], fallback=False)
    assert ai.models == (DEFAULT_MODELS[1],)
    assert ai.allowed_models == DEFAULT_MODELS
    ai.prefer_model()
    assert ai.models == DEFAULT_MODELS and ai.model == DEFAULT_MODELS[0]


def test_manual_selection_cannot_add_unapproved_model():
    ai = GeminiProvider('test-key', models=['approved-only'])
    with pytest.raises(AIError, match='已允許'):
        ai.prefer_model('unapproved-paid-model')
    assert ai.models == ('approved-only',)


def setup_app(monkeypatch, repo, catalog, ai):
    from ui import settings
    monkeypatch.setattr(settings, 'services', lambda: Services(catalog, repo, ai, {}))
    return AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()


def test_selector_default_and_switch_do_not_call_ai_or_modify_draft(monkeypatch, repo, catalog, sdk):
    ai = GeminiProvider('test-key')
    at = setup_app(monkeypatch, repo, catalog, ai)
    assert by_label(at.selectbox, 'AI 模型').value == '自動備援（預設）'
    assert ai.models == DEFAULT_MODELS
    before = at.session_state.draft.model_dump_json()
    by_label(at.selectbox, 'AI 模型').set_value(DEFAULT_MODELS[2]).run()
    assert ai.models == (DEFAULT_MODELS[2], DEFAULT_MODELS[0], DEFAULT_MODELS[1])
    assert not sdk.calls and at.session_state.draft.model_dump_json() == before
    by_label(at.checkbox, '失敗時切換其他備援模型').uncheck().run()
    assert ai.models == (DEFAULT_MODELS[2],)
    by_label(at.selectbox, 'AI 模型').set_value('自動備援（預設）').run()
    assert ai.models == DEFAULT_MODELS and not sdk.calls


def test_selected_model_generates_and_preserves_fallback(monkeypatch, repo, catalog, sdk):
    ai = GeminiProvider('test-key', max_retries=0)
    at = setup_app(monkeypatch, repo, catalog, ai)
    by_label(at.selectbox, 'AI 模型').set_value(DEFAULT_MODELS[2]).run()
    select_topic(at)
    sdk.outcomes = [error(503), title_response()]
    by_label(at.button, '生成標題').click().run()
    assert not at.exception
    assert [c['model'] for c in sdk.calls] == [DEFAULT_MODELS[2], DEFAULT_MODELS[0]]
    assert any(DEFAULT_MODELS[0] in c.value for c in at.caption if '最近一次成功' in c.value)
    assert by_label(at.selectbox, 'AI 模型').value == DEFAULT_MODELS[2]
    assert not repo.list_projects()


def test_fixed_model_does_not_switch_on_failure(monkeypatch, repo, catalog, sdk):
    ai = GeminiProvider('test-key', max_retries=0)
    at = setup_app(monkeypatch, repo, catalog, ai)
    by_label(at.selectbox, 'AI 模型').set_value(DEFAULT_MODELS[1]).run()
    by_label(at.checkbox, '失敗時切換其他備援模型').uncheck().run()
    select_topic(at)
    before = at.session_state.draft.model_dump_json()
    sdk.outcomes = [error(503)]
    by_label(at.button, '生成標題').click().run()
    assert not at.exception and at.error
    assert [c['model'] for c in sdk.calls] == [DEFAULT_MODELS[1]]
    assert at.session_state.draft.model_dump_json() == before


def test_removed_model_resets_to_automatic_and_refresh_uses_default(monkeypatch, repo, catalog, sdk):
    ai = GeminiProvider('test-key')
    at = setup_app(monkeypatch, repo, catalog, ai)
    by_label(at.selectbox, 'AI 模型').set_value(DEFAULT_MODELS[2]).run()
    # Simulate an administrator narrowing the allowlist on the next rerun.
    from ui import settings
    narrowed = GeminiProvider('test-key', models=[DEFAULT_MODELS[0]])
    monkeypatch.setattr(settings, 'services', lambda: Services(catalog, repo, narrowed, {}))
    at.run()
    assert not at.exception
    assert by_label(at.selectbox, 'AI 模型').value == '自動備援（預設）'
    fresh = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
    assert by_label(fresh.selectbox, 'AI 模型').value == '自動備援（預設）'
    assert not sdk.calls
