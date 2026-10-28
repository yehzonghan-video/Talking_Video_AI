"""Isolated synthetic editor smoke check for local and Community Cloud deployments."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import streamlit as st
from core.video.assets import LocalAssets
from core.video.project_manager import VideoProjectManager
from core.video.schemas import VideoProject, Transcript, MediaInfo, Decision
from core.video.timeline import build_timeline
from core.subtitles.service import generate


def create_demo(result, folder):
    """A separate SQLite DB and tiny synthetic source, never a customer project."""
    manager = VideoProjectManager(Path(folder) / 'demo.db')
    assets = LocalAssets(Path(folder) / 'media')
    media = MediaInfo.model_validate(result['media'])
    project = VideoProject(script_id='environment-check', title='合成編輯器測試',
        script_snapshot='繁體字幕室內設計。剪輯後時間同步。', script_version=1,
        original_name='合成測試.mp4', source_sha256='0' * 64, source_suffix='.mp4', media=media,
        transcript=Transcript.model_validate(result['transcript']),
        timelines=[build_timeline(media.duration, [], 1, '合成示範原片')],
        suggestions=[Decision(start=1, end=2, kind='retake', reason='合成示範：可確認刪除中間一秒')])
    _, project.source_sha256 = assets.write_upload(project.id, BytesIO(result['source']), '.mp4', 2_000_000)
    project = generate(manager.save(project), manager)
    return project, manager, assets


def render(result, folder):
    st.caption('以下是獨立的3秒黑底／音調示範，字幕是合成測試資料。可測試播放、編輯、儲存與輸出；不使用正式專案、不呼叫AI／語音辨識。示範與目前瀏覽工作階段共用生命週期。')
    key = '_visual_environment_demo'
    if key not in st.session_state:
        # TemporaryDirectory owns only this generated demo and cleans it when the
        # session releases the object. It never scans/deletes user media folders.
        temporary = TemporaryDirectory(prefix='temp-editor-check-', dir=folder)
        project, _, _ = create_demo(result, temporary.name)
        st.session_state[key] = (temporary, project.id)
    temporary, project_id = st.session_state[key]
    manager = VideoProjectManager(Path(temporary.name) / 'demo.db')
    assets = LocalAssets(Path(temporary.name) / 'media')
    from ui.visual_editor import render as render_editor
    render_editor(manager.get(project_id), manager, assets)
