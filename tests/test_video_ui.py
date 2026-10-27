import pytest
from streamlit.testing.v1 import AppTest
from core.video.project_manager import VideoProjectManager
from core.video.assets import LocalAssets
from core.video.uploader import create_project
from core.workflow import project_from_draft
from ui.settings import Services
from tests.conftest import ROOT
from tests.test_video_media import media_files
from tests.test_ui import by_label


def prepare(monkeypatch, repo, catalog, fake, tmp_path):
    from ui import settings, video
    manager, assets = VideoProjectManager(tmp_path / 'video.db'), LocalAssets(tmp_path / 'media')
    monkeypatch.setattr(settings, 'services', lambda: Services(catalog, repo, fake, {}))
    monkeypatch.setattr(video, 'resources', lambda s: (manager, assets))
    return manager, assets


def open_video():
    at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
    by_label(at.radio, '前往').set_value('AI 影片粗剪').run()
    assert not at.exception
    return at


def test_video_page_without_script_preserves_phase_one(monkeypatch, repo, catalog, fake, tmp_path):
    prepare(monkeypatch, repo, catalog, fake, tmp_path)
    at = open_video()
    assert any('儲存一份腳本' in i.value for i in at.info)
    by_label(at.radio, '前往').set_value('AI 選題').run()
    assert not at.exception and by_label(at.button, '採用這個選題')


def test_saved_project_manual_cut_restore_preview_export(monkeypatch, repo, catalog, fake, tmp_path, draft, media_files):
    manager, assets = prepare(monkeypatch, repo, catalog, fake, tmp_path)
    script = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    with media_files['mp4'].open('rb') as upload:
        project = create_project(script, upload, 'source.mp4', assets, manager)
    at = open_video()
    by_label(at.checkbox, '我已聽過這一段，確認刪除').check()
    by_label(at.number_input, '手動刪除開始（秒）').set_value(1.7)
    by_label(at.number_input, '手動刪除結束（秒）').set_value(3.8)
    by_label(at.button, '加入並保存新版本').click().run()
    assert not at.exception
    assert len(manager.get(project.id).timelines) == 2
    by_label(at.button, '產生粗剪預覽').click().run()
    assert not at.exception and assets.path(project.id, 'preview-2.mp4').exists()
    by_label(at.checkbox, '我已確認目前已保存的剪輯內容，準備輸出 MP4').check().run()
    by_label(at.button, '輸出 MP4').click().run()
    saved = manager.get(project.id)
    assert not at.exception and saved.export_status == '已輸出'
    assert assets.path(saved.id, saved.output_key).is_file()
    # A fresh browser session recovers the confirmed cut, independently of Session State.
    fresh = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30)
    fresh.query_params['video'] = saved.id
    fresh.run()
    assert not fresh.exception
    assert by_label(fresh.radio, '前往').value == 'AI 影片粗剪'
    assert len(manager.get(saved.id).timelines[-1].keep_segments) == 2


def test_manual_cut_requires_confirmation(monkeypatch, repo, catalog, fake, tmp_path, draft, media_files):
    manager, assets = prepare(monkeypatch, repo, catalog, fake, tmp_path)
    script = repo.save(project_from_draft(draft, catalog.combo_id(draft.selection)))
    with media_files['silent'].open('rb') as upload:
        p = create_project(script, upload, 'silent.mp4', assets, manager)
    at = open_video()
    by_label(at.button, '加入並保存新版本').click().run()
    assert not at.exception and any('先勾選' in e.value for e in at.error)
    assert len(manager.get(p.id).timelines) == 1
