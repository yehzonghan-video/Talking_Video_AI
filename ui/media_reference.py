"""Small Streamlit 1.65 adapter: register bytes once and renew session references.

The SDK's normal add(path) re-reads and hashes the entire file on every rerun.
All private SDK access lives here and is tested against the pinned SDK version.
"""
from pathlib import Path
import streamlit as st
from streamlit import runtime
from streamlit.runtime.scriptrunner import get_script_run_ctx
from core.video.errors import VideoError


def video_reference(source, project_id):
    source = Path(source).resolve()
    stat = source.stat()
    token = (str(source), stat.st_size, stat.st_mtime_ns)
    if not runtime.exists():
        return ''  # AppTest has no HTTP media server.
    manager = runtime.get_instance().media_file_mgr
    context = get_script_run_ctx()
    if context is None:
        raise VideoError('影片播放工作階段已結束，請重新整理。')
    coordinate = 'visual-editor-' + project_id
    refs = st.session_state.setdefault('_editor_media_refs', {})
    previous = refs.get(project_id)
    if previous and tuple(previous['token']) == token:
        with manager._lock:
            if previous['id'] in manager._file_metadata:
                manager._files_by_session_and_coord[context.session_id][coordinate] = previous['id']
                return previous['url']
    url = manager.add(str(source), 'video/quicktime' if source.suffix.lower() == '.mov' else 'video/mp4', coordinate)
    file_id = Path(url.split('?')[0]).stem
    refs[project_id] = {'token': token, 'id': file_id, 'url': url}
    return url
