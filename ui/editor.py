import streamlit as st
from core.ai.script_generator import generate_script
from core.ai.conversation import revise
from core.storage.schemas import json_text
from core.workflow import checkpoint, propose, accept, cancel, restore, project_from_draft
from ui.state import edit_callback, persist, refresh
from ui.topics import describe

QUICK = ["簡短一點", "詳細一點", "更口語化", "更專業", "強化前三秒", "重新生成"]


def request_revision(s, request):
    d = st.session_state.draft
    with st.spinner("正在依照你的要求修改…"):
        result = revise(s.provider, s.catalog.context(d.selection), d.title, d.script, d.duration,
                        [t.model_dump() for t in d.history], request, s.config)
    propose(d, result.script, request, result.explanation)
    refresh(s)


def render(s):
    st.header("腳本編輯")
    d = st.session_state.draft
    if not d.selection:
        st.info("請先到「AI 選題」採用一組 ABC 分類。")
        return
    with st.expander("查看選題資訊"):
        describe(s.catalog, d.selection)
    st.text_input("影片標題", key="edit_title", max_chars=200, on_change=edit_callback, args=(s, "title"))
    left, right = st.columns(2)
    left.selectbox("目標影片長度", [30, 45, 60], format_func=lambda v: f"{v}秒", key="edit_duration", on_change=edit_callback, args=(s, "duration"))
    from core.storage.schemas import STATUSES
    right.selectbox("製作狀態", STATUSES, key="edit_status", on_change=edit_callback, args=(s, "status"))
    if not d.script:
        if st.button("生成逐字稿", type="primary", disabled=not d.title.strip()):
            with st.spinner("正在撰寫口播逐字稿…"):
                result = generate_script(s.provider, s.catalog.context(d.selection), d.title, d.duration, s.config)
            d.script = result.text()
            checkpoint(d, "AI 初稿")
            refresh(s)
    st.text_area("逐字稿（可直接修改）", key="edit_script", height=330, max_chars=20000,
        on_change=edit_callback, args=(s, "script"), help="輸入後點一下欄位外，內容便會暫存在本機。")
    estimate = round(len("".join(d.script.split())) / s.config.get("characters_per_second", 3.5))
    st.caption(f"約 {len(''.join(d.script.split()))} 字 · 口播估計約 {estimate} 秒，實際長度依個人語速而異。")
    if st.button("確認手動編輯為新版本", disabled=not (d.title.strip() and d.script.strip()) or bool(d.pending)):
        checkpoint(d, "確認手動編輯")
        persist(s)
        st.success("已確認目前版本。")
    if d.script:
        st.subheader("與 AI 一起調整")
        with st.expander("對話紀錄", expanded=False):
            if not d.history:
                st.caption("尚未開始對話。")
            for turn in d.history:
                with st.chat_message("user"):
                    st.write(turn.request)
                with st.chat_message("assistant"):
                    st.write(turn.explanation)
                    st.caption(turn.outcome)
                    st.text(turn.proposal)
        cols = st.columns(3)
        for i, label in enumerate(QUICK):
            if cols[i % 3].button(label, disabled=bool(d.pending) or not d.title.strip(), use_container_width=True):
                request_revision(s, label)
        request = st.chat_input("告訴 AI 想修改哪裡，例如：把第二段講得更自然", disabled=bool(d.pending) or not d.title.strip(), max_chars=5000)
        if request:
            request_revision(s, request)
    if d.pending:
        st.subheader("修改提案 · 等你確認")
        st.info(d.pending.explanation)
        before, after = st.columns(2)
        with before:
            st.markdown("**修改前**")
            st.text(d.pending.base_script)
        with after:
            st.markdown("**完整新版逐字稿**")
            st.text(d.pending.script)
        a, b = st.columns(2)
        if a.button("確認套用修改", type="primary"):
            accept(d)
            refresh(s)
        if b.button("取消這次修改"):
            cancel(d)
            refresh(s)
    if d.versions:
        with st.expander(f"版本紀錄（共 {len(d.versions)} 版）"):
            number = st.selectbox("選擇版本", [v.number for v in d.versions],
                format_func=lambda n: f"V{n} · {d.versions[n - 1].note}", key="version_choice")
            v = d.versions[number - 1]
            st.write(v.title)
            st.text(v.script)
            st.caption(f"目標 {v.duration} 秒 · {v.created_at}")
            if st.button("恢復這個版本（保留後續紀錄）", disabled=bool(d.pending)):
                restore(d, number)
                refresh(s)
    st.divider()
    if st.button("儲存腳本", type="primary", disabled=not (d.title.strip() and d.script.strip()) or bool(d.pending)):
        project = project_from_draft(d, s.catalog.combo_id(d.selection))
        saved = s.repo.save(project)
        d.saved_revision = saved.revision
        persist(s)
        st.success("腳本已儲存於目前主機，並將此組合標記為已使用。請定期下載 JSON 備份。")
    col1, col2 = st.columns(2)
    col1.download_button("下載目前逐字稿 TXT", d.title + "\n\n" + d.script,
        file_name="口播逐字稿.txt", mime="text/plain", disabled=not bool(d.script))
    col2.download_button("下載草稿 JSON（含待確認提案）", json_text(d), file_name="口播草稿.json", mime="application/json")
    st.caption("草稿暫存不等同正式儲存。欄位離開焦點後才會同步；尚未同步的輸入可能因重新整理遺失。")
