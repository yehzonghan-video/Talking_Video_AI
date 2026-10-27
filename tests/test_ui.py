import streamlit as st
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


def test_full_user_journey(monkeypatch, repo, catalog, fake):
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
