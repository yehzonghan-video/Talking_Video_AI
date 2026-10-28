"""One stable, eagerly registered download per completed output.

Streamlit 1.65 deferred callables leave the actual media ID unreferenced.
Registering bytes through download_button instead pins it to the active session
and avoids a second generate/download request. Streamlit still holds these bytes
in memory; this is not a streaming object-storage implementation.
"""
from pathlib import Path
import streamlit as st
from core.video.diagnostics import record, exception_details
from core.video.errors import VideoError
from core.video.timeline import filename


def mp4_download(project, assets):
    path = assets.path(project.id, project.output_key)
    refs = st.session_state.setdefault('_mp4_download_refs', {})
    refs[project.id] = project.output_key  # Reference only, no second copy of bytes.
    try:
        size = path.stat().st_size
        record('download_registered', exists=True, bytes=size, session_reference=refs.get(project.id) == project.output_key)
        if size <= 0:
            raise VideoError('輸出 MP4 是空檔，請重新輸出影片。')
        data = path.read_bytes()
        if len(data) != size:
            raise VideoError('輸出檔案讀取不完整，請重新輸出影片。')
        st.download_button('下載 MP4', data=data, file_name=filename(project.title), mime='video/mp4',
            on_click='ignore', key='mp4_download_' + project.id)
        if size > 200 * 1024**2:
            st.caption('此 MP4 超過200 MB，雲端下載可能較慢；請保持頁面開啟。大型影片建議使用本機版本。')
    except (OSError, MemoryError, VideoError) as exc:
        record('download_failed', exists=path.exists(), **exception_details(exc))
        st.error('無法讀取輸出影片供下載，請重新開啟專案或查看伺服器下載診斷。' if not isinstance(exc, MemoryError)
                 else '雲端記憶體不足以準備此 MP4 下載，請改用較短影片或本機版本。')
