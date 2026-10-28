"""Streamlit entry point. Core modules remain independently reusable."""
import streamlit as st
from pydantic import ValidationError
from core.ai.provider import AIError
from core.storage.project_manager import StorageError
from core.storage.schemas import Draft
from core.topics.combinations import ExhaustedTopics
from core.workflow import WorkflowError
from core.video.errors import VideoError
from ui import topics, editor, library, video
from ui.settings import services
from ui.model_selector import render_model_selector
from ui.state import initialize, switch, persist

st.set_page_config(page_title="口播企劃室", page_icon="✦", layout="wide")


# A safe, once-per-process release marker makes Cloud source synchronisation
# distinguishable from browser reloads and cached imported modules.  It must be
# declared after ``set_page_config`` because that Streamlit call has to be first.
@st.cache_resource
def report_release(release):
    from streamlit.logger import get_logger
    get_logger('talking_video.deployment').info('app_release=%s', release)


report_release('2026.10.28-visual-r1')
st.markdown("""<style>
.block-container {max-width:1100px;padding-top:2.2rem}
h1,h2,h3 {letter-spacing:.02em}
[data-testid="stSidebar"] {background:#f3f5f2}
.stButton>button {border-radius:10px;min-height:2.8rem}
</style>""", unsafe_allow_html=True)
st.title("口播企劃室")
st.caption("從一個好問題，開始一支好影片。")


def main():
    s = services()
    initialize(s)
    with st.sidebar:
        st.markdown("### 製作流程")
        page = st.radio("前往", ["AI 選題", "腳本編輯", "腳本資料庫", "AI 影片粗剪"], index=3 if st.query_params.get('video') else 0, key='navigation', label_visibility="collapsed")
        st.divider()
        render_model_selector(s.provider)
        st.info("目前資料保存在本機／目前雲端主機。雲端重啟或重新部署可能遺失，請定期下載 JSON 備份。")
        if not s.provider.api_key:
            st.warning("尚未設定 AI 金鑰，可先手動編寫及管理腳本。")
        if st.session_state.get('last_ai_model'):
            st.caption('最近一次成功生成使用模型：' + st.session_state.last_ai_model)
        st.caption("目前草稿：" + (st.session_state.draft.title or "未命名"))
        if st.button("新增空白草稿"):
            switch(s, Draft())
        with st.expander("最近暫存的草稿"):
            for token, draft in s.repo.list_drafts()[:20]:
                if st.button(draft.title or "未命名草稿", key="resume_" + token):
                    switch(s, draft, token)
            st.caption("重新整理會依網址恢復草稿；請勿把含草稿識別碼的網址分享給他人。")
    try:
        {"AI 選題": topics.render, "腳本編輯": editor.render, "腳本資料庫": library.render, "AI 影片粗剪": video.render}[page](s)
    finally:
        # st.rerun also executes finally; retain metadata without issuing another request.
        if getattr(s.provider, 'last_model', None):
            st.session_state.last_ai_model = s.provider.last_model
    persist(s)


try:
    main()
except (AIError, StorageError, ExhaustedTopics, WorkflowError, VideoError) as exc:
    st.error(str(exc))
except (ValueError, ValidationError) as exc:
    st.error("資料驗證未通過，請檢查輸入或備份檔案。現有內容已保留。")
except OSError:
    st.error("無法讀取設定或資料檔案，請確認分類檔與資料資料夾可用。")
