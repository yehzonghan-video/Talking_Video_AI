import streamlit as st
import pytest
from streamlit.testing.v1 import AppTest
from core.ai.provider import AIError, GeminiProvider
from core.storage.schemas import Draft
from core.workflow import open_project
from ui.settings import Services
from tests.conftest import ROOT


def by_label(elements, label):
    return next(e for e in elements if e.label == label)


def app(monkeypatch, repo, catalog, fake):
    from ui import settings
    svc = Services(catalog, repo, fake, {"characters_per_second": 3.5})
    monkeypatch.setattr(settings, "services", lambda: svc)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    assert not at.exception
    return at


def select_topic(at):
    by_label(at.button, "採用這個選題").click().run()
    assert at.session_state.draft.selection is not None


def navigate(at, page):
    by_label(at.radio, "前往").set_value(page).run()
    assert not at.exception


def generate(at):
    select_topic(at)
    by_label(at.button, "生成標題").click().run()
    by_label(at.button, "採用標題").click().run()
    navigate(at, "腳本編輯")
    by_label(at.button, "生成逐字稿").click().run()
    assert not at.exception


@pytest.mark.parametrize("title_count", [1, 5])
def test_full_user_journey(monkeypatch, repo, catalog, fake, title_count):
    fake.title_count = title_count
    at = app(monkeypatch, repo, catalog, fake)
    generate(at)
    initial = at.session_state.draft.script
    assert repo.used() == set()
    by_label(at.button, "更口語化").click().run()
    assert at.session_state.draft.pending is not None
    assert at.session_state.draft.script == initial
    by_label(at.button, "取消這次修改").click().run()
    assert at.session_state.draft.script == initial
    at.chat_input[0].set_value("把開頭講得自然一點").run()
    by_label(at.button, "確認套用修改").click().run()
    assert len(at.session_state.draft.versions) == 2
    by_label(at.button, "簡短一點").click().run()
    by_label(at.button, "確認套用修改").click().run()
    assert len(at.session_state.draft.versions) == 3
    assert len(fake.calls[-1][1]["history"]) == 2
    by_label(at.button, "儲存腳本").click().run()
    assert len(repo.list_projects()) == 1 and len(repo.used()) == 1
    navigate(at, "腳本資料庫")
    by_label(at.button, "開啟腳本繼續編輯").click().run()
    navigate(at, "腳本編輯")
    assert at.session_state.draft.saved_revision == 1
    at.selectbox(key="version_choice").set_value(1).run()
    by_label(at.button, "恢復這個版本（保留後續紀錄）").click().run()
    assert at.session_state.draft.script == initial
    by_label(at.button, "儲存腳本").click().run()
    assert repo.list_projects()[0].revision == 2
    assert not at.exception


@pytest.mark.parametrize("count", range(1, 6))
@pytest.mark.parametrize("status", ["適合", "可延伸"])
def test_title_picker_handles_all_counts_and_statuses(monkeypatch, repo, catalog, fake, count, status):
    fake.title_count, fake.title_status = count, status
    at = app(monkeypatch, repo, catalog, fake)
    select_topic(at)
    selection = dict(at.session_state.draft.selection)
    by_label(at.button, "生成標題").click().run()
    picker = by_label(at.radio, "選擇標題")
    assert len(fake.calls) == 1
    assert len(picker.options) == count
    assert at.session_state.draft.title_result["status"] == status
    notices = at.success if status == "適合" else at.info
    assert any(status + "｜" in n.value for n in notices)
    picker.set_value(picker.options[-1]).run()
    chosen = by_label(at.radio, "選擇標題").value
    by_label(at.button, "採用標題").click().run()
    assert at.session_state.draft.title == chosen
    navigate(at, "腳本編輯")
    at.text_input(key="edit_title").set_value("我的手動標題").run()
    navigate(at, "AI 選題")
    fake.title_count = 1 if count > 1 else 5
    by_label(at.button, "重新生成標題").click().run()
    assert at.session_state.draft.selection == selection
    assert at.session_state.draft.title == "我的手動標題"
    assert len(by_label(at.radio, "選擇標題").options) == fake.title_count
    assert not at.exception


def test_not_recommended_ui_allows_manual_title_or_alternative(monkeypatch, repo, catalog, fake):
    fake.title_status = "不建議"
    at = app(monkeypatch, repo, catalog, fake)
    select_topic(at)
    by_label(at.button, "生成標題").click().run()
    assert not at.exception
    assert not any(r.label == "選擇標題" for r in at.radio)
    assert any("不建議｜" in n.value for n in at.warning)
    alternative = next(b for b in at.button if b.label.startswith("改用："))
    alternative.click().run()
    assert at.session_state.draft.selection == dict(a="A02", b="B01", c="C03")
    by_label(at.button, "生成標題").click().run()
    navigate(at, "腳本編輯")
    at.text_input(key="edit_title").set_value("自行選擇的切入點").run()
    by_label(at.button, "生成逐字稿").click().run()
    by_label(at.button, "儲存腳本").click().run()
    assert repo.list_projects()[0].title == "自行選擇的切入點"


@pytest.mark.parametrize("reasonable", [True, False])
def test_old_cached_titles_remain_selectable_without_storage_migration(monkeypatch, repo, catalog, fake, reasonable):
    at = app(monkeypatch, repo, catalog, fake)
    select_topic(at)
    draft = at.session_state.draft
    draft.title_result = dict(reasonable=reasonable, reason="舊版評估", alternatives=[], titles=["舊標題一", "舊標題二"])
    repo.save_draft(at.session_state.draft_id, draft)
    token = at.session_state.draft_id
    fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
    fresh.query_params["draft"] = token
    fresh.run()
    assert not fresh.exception
    assert any("舊版生成結果" in n.value for n in fresh.info)
    by_label(fresh.radio, "選擇標題").set_value("舊標題二").run()
    by_label(fresh.button, "採用標題").click().run()
    assert fresh.session_state.draft.title == "舊標題二"


def test_bad_title_response_preserves_previous_topics(monkeypatch, repo, catalog, fake):
    at = app(monkeypatch, repo, catalog, fake)
    select_topic(at)
    by_label(at.button, "生成標題").click().run()
    before = at.session_state.draft.model_dump_json()
    fake.title_count = 0
    by_label(at.button, "重新生成標題").click().run()
    assert not at.exception and at.error
    assert at.session_state.draft.model_dump_json() == before


def test_no_key_is_recoverable(monkeypatch, repo, catalog):
    at = app(monkeypatch, repo, catalog, GeminiProvider("", "model"))
    select_topic(at)
    by_label(at.button, "生成標題").click().run()
    assert not at.exception
    assert any("尚未設定" in e.value for e in at.error)
    navigate(at, "腳本編輯")
    at.text_input(key="edit_title").set_value("手動標題").run()
    at.text_area(key="edit_script").set_value("手動逐字稿內容").run()
    by_label(at.button, "儲存腳本").click().run()
    assert len(repo.list_projects()) == 1


def test_ai_failure_preserves_draft(monkeypatch, repo, catalog, fake):
    at = app(monkeypatch, repo, catalog, fake)
    generate(at)
    before = at.session_state.draft.model_dump_json()
    fake.failure = AIError("AI 回傳格式不完整，原有內容已保留。")
    by_label(at.button, "更專業").click().run()
    assert not at.exception
    assert at.session_state.draft.model_dump_json() == before
    token = at.session_state.draft_id
    assert repo.load_draft(token).model_dump_json() == before


def test_refresh_recovers_manual_edits(monkeypatch, repo, catalog, fake):
    at = app(monkeypatch, repo, catalog, fake)
    generate(at)
    at.text_area(key="edit_script").set_value("這是我手動修改的內容").run()
    token = at.session_state.draft_id
    fresh = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15)
    fresh.query_params["draft"] = token
    fresh.run()
    assert fresh.session_state.draft.script == "這是我手動修改的內容"
    assert not fresh.exception


def test_random_ui(monkeypatch, repo, catalog, fake):
    at = app(monkeypatch, repo, catalog, fake)
    by_label(at.radio, "選題方式").set_value("完全隨機").run()
    by_label(at.button, "隨機選題").click().run()
    select_topic(at)
    catalog.validate(at.session_state.draft.selection)
    by_label(at.radio, "選題方式").set_value("條件隨機").run()
    at.checkbox(key="fix_a").check().run()
    at.checkbox(key="fix_b").check().run()
    at.selectbox(key="pick_條件隨機_a").set_value("A07").run()
    at.selectbox(key="pick_條件隨機_b").set_value("B03").run()
    by_label(at.button, "隨機選題").click().run()
    assert at.session_state.candidate["a"] == "A07"
    assert at.session_state.candidate["b"] == "B03"
    assert not at.exception
