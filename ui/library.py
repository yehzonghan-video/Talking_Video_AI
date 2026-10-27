from uuid import uuid4
import streamlit as st
from core.storage.project_manager import export_backup, export_txt, parse_backup, import_backup
from core.storage.schemas import Draft
from core.workflow import open_project
from ui.state import switch
from ui.topics import LABELS


def render(s):
    st.header("腳本資料庫")
    projects = s.repo.list_projects()
    search = st.text_input("搜尋標題")
    from core.storage.schemas import STATUSES
    status = st.selectbox("製作狀態篩選", ["全部"] + STATUSES)
    filters = {}
    for col, (dim, group) in zip(st.columns(3), s.catalog.groups.items()):
        filters[dim] = col.selectbox(LABELS[dim] + "篩選", [""] + list(group),
            format_func=lambda cid, g=group: "全部" if not cid else g[cid].name, key="filter_" + dim)
    filtered = [p for p in projects if search.casefold() in p.title.casefold() and
        (status == "全部" or p.status == status) and all(not cid or p.selection[dim] == cid for dim, cid in filters.items())]
    st.caption(f"顯示 {len(filtered)} / {len(projects)} 份腳本")
    if not filtered:
        st.info("尚無符合條件的腳本，完成編輯後記得按「儲存腳本」。")
    for p in filtered:
        with st.expander(f"{p.title}　｜{p.status} · {p.duration}秒 · V{len(p.versions)}"):
            st.caption(" × ".join(s.catalog.groups[dim][cid].name for dim, cid in p.selection.items()))
            st.caption(f"建立：{p.created_at} · 最後修改：{p.updated_at}")
            st.text(p.script)
            if st.button("開啟腳本繼續編輯", key="open_" + p.id):
                switch(s, open_project(p))
            st.caption("開啟後請切換到「腳本編輯」。目前草稿會保留在側欄的草稿紀錄。")
            c1, c2 = st.columns(2)
            c1.download_button("匯出 TXT", export_txt(p), file_name=f"{p.id}.txt", mime="text/plain", key="txt_" + p.id)
            c2.download_button("匯出 JSON（含版本）", export_backup(s.repo, [p]), file_name=f"{p.id}.json", mime="application/json", key="json_" + p.id)
            confirmed = st.checkbox("確認刪除此腳本（保留選題使用紀錄）", key="delete_confirm_" + p.id)
            if st.button("刪除腳本", key="delete_" + p.id, disabled=not confirmed):
                s.repo.delete(p.id, p.revision)
                st.rerun()
    st.divider()
    st.subheader("備份與恢復")
    st.download_button("下載全部腳本 JSON 備份", export_backup(s.repo), file_name="口播腳本備份.json", mime="application/json")
    st.caption("備份包含全部正式腳本、版本、對話與組合使用紀錄。未儲存草稿請在腳本編輯頁另外下載。")
    upload = st.file_uploader("匯入腳本 JSON 備份", type=["json"], key="backup_upload")
    if upload:
        content = upload.getvalue()
        backup = parse_backup(content, s.catalog)
        existing = {p.id for p in projects}
        conflicts = sum(p.id in existing for p in backup.projects)
        st.info(f"檔案驗證通過：{len(backup.projects)} 份腳本；{conflicts} 份 ID 已存在，匯入時會保留現有資料並略過。")
        if st.checkbox("確認合併匯入，保留目前所有腳本") and st.button("開始恢復資料"):
            added, skipped = import_backup(s.repo, content, s.catalog)
            st.success(f"已匯入 {added} 份，略過 {skipped} 份重複腳本。")
    with st.expander("恢復尚未儲存的草稿"):
        draft_upload = st.file_uploader("選擇「口播草稿.json」", type=["json"], key="draft_upload")
        if draft_upload:
            d = Draft.model_validate_json(draft_upload.getvalue())
            if d.selection:
                s.catalog.validate(d.selection)
            # Restore as an independent script so it cannot overwrite an existing one.
            d.project_id, d.saved_revision, d.title_result = str(uuid4()), 0, None
            st.write(d.title or "未命名草稿")
            if st.button("恢復為獨立草稿"):
                switch(s, d)
