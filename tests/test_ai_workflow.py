import pytest
from pydantic import ValidationError
from core.ai.provider import GeminiProvider, AIError
from core.ai.title_generator import generate_titles, TitleResult
from core.ai.script_generator import generate_script
from core.ai.conversation import revise
from core.workflow import propose, accept, cancel, restore, checkpoint


def test_five_titles(fake, catalog):
    selection = dict(a="A01", b="B01", c="C03")
    result = generate_titles(fake, catalog.context(selection), {}, {"industry": "測試產業"})
    assert len({idea.title for idea in result.titles}) == 5
    assert "keywords" in fake.calls[0][1]["topic"]["a"]


@pytest.mark.parametrize("count", range(1, 6))
@pytest.mark.parametrize("status", ["適合", "可延伸"])
def test_flexible_title_count_and_positive_status(fake, catalog, count, status):
    fake.title_count, fake.title_status = count, status
    selection = dict(a="A04", b="B03", c="C09")
    result = generate_titles(fake, catalog.context(selection), {}, {})
    assert result.status == status and len(result.titles) == count
    assert all(idea.title and idea.topic for idea in result.titles)
    assert not result.alternatives
    prompt = fake.calls[-1][0]
    assert "生活情境" in prompt and "不可只按分類表面關聯否定" in prompt
    assert "只有一題也可以" in prompt and "同一內容換句話說" in prompt


def test_not_recommended_only_offers_alternatives(fake, catalog):
    fake.title_status = "不建議"
    result = generate_titles(fake, catalog.context(dict(a="A01", b="B01", c="C01")), {}, {})
    assert result.titles == [] and len(result.alternatives) == 1


@pytest.mark.parametrize("status,titles,alternatives", [
    ("可延伸", [], []),
    ("不建議", [], []),
    ("不建議", [dict(title="可信的標題", topic="已有可信切入點就不應標為不建議。")], [dict(a="A01", b="B01", c="C01")]),
    ("適合", [dict(title="標題", topic="具體知識")], [dict(a="A01", b="B01", c="C01")]),
    ("其他", [dict(title="標題", topic="具體知識")], []),
])
def test_conflicting_status_and_content_rejected(status, titles, alternatives):
    with pytest.raises(ValidationError):
        TitleResult(status=status, reason="理由", titles=titles, alternatives=alternatives)


@pytest.mark.parametrize("ideas", [
    [dict(title="標題一", topic="同一個問題"), dict(title="標題二", topic="同一個問題。")],
    [dict(title="同一標題", topic="問題一"), dict(title="同一標題！", topic="問題二")],
    [dict(title="標題", topic="   ")],
    [dict(title="標題", topic="……")],
])
def test_repeated_or_empty_concrete_topics_rejected(ideas):
    with pytest.raises(ValidationError):
        TitleResult(status="適合", reason="理由", titles=ideas, alternatives=[])


@pytest.mark.parametrize("seconds", [30, 45, 60])
def test_duration(fake, catalog, seconds):
    result = generate_script(fake, catalog.context(dict(a="A01", b="B01", c="C01")), "標題", seconds, {})
    assert str(seconds) in result.body
    assert len(result.text().split("\n\n")) == 3


def test_multi_turn_preview_cancel_restore(fake, draft):
    original = draft.script
    result = revise(fake, {}, draft.title, draft.script, 45, [], "開頭更自然", {})
    propose(draft, result.script, "開頭更自然", result.explanation)
    assert draft.script == original and len(draft.versions) == 1
    accept(draft)
    assert len(draft.versions) == 2 and draft.script != original
    result2 = revise(fake, {}, draft.title, draft.script, 45, [t.model_dump() for t in draft.history], "簡短一點", {})
    assert fake.calls[-1][1]["current_script"] == draft.script
    assert fake.calls[-1][1]["history"][0]["outcome"] == "已套用"
    propose(draft, result2.script, "簡短一點", result2.explanation)
    confirmed = draft.script
    cancel(draft)
    assert draft.script == confirmed and len(draft.versions) == 2
    assert draft.history[-1].outcome == "已取消"
    restore(draft, 1)
    assert draft.script == original and len(draft.versions) == 3


def test_stale_preview_never_overwrites_manual(draft):
    propose(draft, "AI 新稿", "改短", "縮短內容")
    draft.script = "使用者剛改過的新內容"
    with pytest.raises(ValueError, match="目前內容已變更"):
        accept(draft)
    assert draft.script == "使用者剛改過的新內容"
    assert draft.pending is not None


def test_version_checkpoint_idempotent_and_manual_preserved(draft):
    checkpoint(draft, "重複確認")
    assert len(draft.versions) == 1
    draft.script = "手動內容"
    restore(draft, 1)
    assert draft.versions[-2].script == "手動內容"
    assert len(draft.versions) == 3


def test_missing_key():
    with pytest.raises(AIError, match="尚未設定"):
        GeminiProvider("", "model").generate("test", {}, TitleResult)


@pytest.mark.parametrize("titles", [["一"] * 5, [], ["", "二", "三", "四", "五"], ["一", "二", "三", "四", "五", "六"]])
def test_bad_titles(titles):
    with pytest.raises(ValidationError):
        TitleResult(status="適合", reason="理由", alternatives=[],
                    titles=[dict(title=t, topic=f"不同具體問題{i}") for i, t in enumerate(titles)])


def test_sdk_bad_response_is_sanitized(monkeypatch, draft):
    from google import genai
    class Client:
        def __init__(self, **kwargs):
            self.models = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def generate_content(self, **kwargs):
            return type("Response", (), {"text": "broken-json"})()
    monkeypatch.setattr(genai, "Client", Client)
    before = draft.model_dump_json()
    with pytest.raises(AIError, match="格式"):
        GeminiProvider("private-key", "model").generate("test", {}, TitleResult)
    assert draft.model_dump_json() == before


def test_sdk_secret_not_exposed(monkeypatch):
    from google import genai
    def fail(**kwargs):
        raise RuntimeError("key=private-key")
    monkeypatch.setattr(genai, "Client", fail)
    with pytest.raises(AIError) as caught:
        GeminiProvider("private-key", "model").generate("test", {}, TitleResult)
    assert "private-key" not in str(caught.value)


@pytest.mark.parametrize("code,notice", [(503, "需求過高"), (504, "逾時"), (401, "驗證失敗")])
def test_service_errors_are_actionable_without_exposing_secrets(monkeypatch, code, notice):
    from google import genai
    class ServiceFailure(RuntimeError):
        pass
    def fail(**kwargs):
        error = ServiceFailure("key=private-key")
        error.code = code
        raise error
    monkeypatch.setattr(genai, "Client", fail)
    with pytest.raises(AIError) as caught:
        GeminiProvider("private-key", "model").generate("test", {}, TitleResult)
    assert notice in str(caught.value)
    assert "原有內容已保留" in str(caught.value)
    assert "private-key" not in str(caught.value)
