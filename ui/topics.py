import streamlit as st
from core.ai.title_generator import generate_titles
from core.ai.provider import AIError
from core.storage.schemas import Draft
from core.topics.combinations import choose
from core.topics.validator import validate_alternatives
from ui.state import persist, refresh, switch

LABELS = {"a": "公司業務", "b": "目標客群", "c": "問題角度"}


def describe(catalog, selection):
    for dim, category in catalog.context(selection).items():
        st.markdown(f"**{LABELS[dim]}｜{category['name']}**")
        st.caption(category["description"] + "　關鍵字：" + "、".join(category["keywords"]))


def render(s):
    st.header("AI 選題")
    st.write("從業務、客群與問題角度，找到下一支影片的主題。")
    st.caption(f"共 {s.catalog.total:,} 組選題 · 已使用 {len(s.repo.used()):,} 組 · 預覽與抽取不計入使用")
    mode = st.radio("選題方式", ["手動選題", "完全隨機", "條件隨機"], horizontal=True)
    fixed = {}
    cols = st.columns(3)
    for col, (dim, group) in zip(cols, s.catalog.groups.items()):
        with col:
            active = mode == "手動選題"
            if mode == "條件隨機":
                active = st.checkbox(f"固定{LABELS[dim]}", key="fix_" + dim)
            ids = list(group)
            current = (st.session_state.draft.selection or {}).get(dim, ids[0])
            selected = st.selectbox(LABELS[dim], ids, index=ids.index(current),
                format_func=lambda cid, g=group: g[cid].name, key=f"pick_{mode}_{dim}", disabled=not active)
            if active:
                fixed[dim] = selected
    reuse = st.checkbox("允許重用已使用組合", disabled=mode == "手動選題")
    if mode == "手動選題":
        candidate = fixed
    else:
        if st.button("使用固定組合" if len(fixed) == 3 else "隨機選題", type="primary"):
            st.session_state.candidate = choose(s.catalog, s.repo.used(), fixed, reuse)
            st.session_state.candidate_conditions = (mode, dict(fixed))
        candidate = st.session_state.get("candidate") if st.session_state.get("candidate_conditions") == (mode, fixed) else None
    if candidate:
        with st.container(border=True):
            st.subheader("選題預覽")
            describe(s.catalog, candidate)
            if s.catalog.combo_id(candidate) in s.repo.used():
                st.info("這組選題曾儲存過腳本，仍可建立另一支影片。")
            d = st.session_state.draft
            changing = d.selection != candidate and bool(d.title or d.script or d.versions)
            confirmed = st.checkbox("保留目前草稿，另建新選題", key="confirm_topic") if changing else True
            if st.button("採用這個選題", disabled=not confirmed):
                if changing:
                    switch(s, Draft(selection=candidate))
                if d.selection != candidate:
                    d.selection = candidate
                    d.title_result = None
                refresh(s)
    d = st.session_state.draft
    st.divider()
    st.subheader("目前採用的選題")
    if not d.selection:
        st.info("先採用一個選題，再生成標題。")
        return
    st.write(" × ".join(s.catalog.groups[dim][cid].name for dim, cid in d.selection.items()))
    if st.button("重新生成標題" if d.title_result else "生成標題", type="primary"):
        with st.spinner("正在尋找生活情境與具體選題…"):
            result = generate_titles(s.provider, s.catalog.context(d.selection),
                {dim: [dict(id=c.id, name=c.name, description=c.description, keywords=c.keywords) for c in group.values()]
                 for dim, group in s.catalog.groups.items()}, s.config)
            try:
                validate_alternatives(s.catalog, [a.model_dump() for a in result.alternatives])
            except ValueError as exc:
                raise AIError("AI 建議包含不存在的分類，請重新生成。原有標題已保留。") from exc
            d.title_result = result.model_dump()
            persist(s)
            st.rerun()
    if d.title_result:
        result = d.title_result
        status = result.get("status")
        if status == "適合":
            st.success("適合｜" + result["reason"])
        elif status == "可延伸":
            st.info("可延伸｜" + result["reason"])
        elif status == "不建議":
            st.warning("不建議｜" + result["reason"] + " 可改用下方替代組合，或到腳本編輯手動填入標題繼續。")
        else:
            # Old drafts retain their selectable titles without altering stored data.
            st.info("這是舊版生成結果，仍可採用原標題；重新生成會依新的生活情境與選題規則評估。")
        for index, alt in enumerate(result["alternatives"]):
            label = " × ".join(s.catalog.groups[dim][cid].name for dim, cid in alt.items())
            if st.button("改用：" + label, key=f"alternative_{index}"):
                if d.script or d.versions or d.title:
                    switch(s, Draft(selection=alt))
                d.selection, d.title_result = alt, None
                refresh(s)
        ideas = result["titles"]
        titles = [idea if isinstance(idea, str) else idea["title"] for idea in ideas]
        if titles:
            st.caption(f"找到 {len(titles)} 個選題；依實際可延伸內容提供，不強制湊滿五個。")
            chosen = st.radio("選擇標題", titles, key="suggested_" + str(hash(tuple(titles))))
            idea = ideas[titles.index(chosen)]
            if isinstance(idea, dict):
                st.write("具體選題：" + idea["topic"])
            if st.button("採用標題"):
                if d.script and chosen != d.title:
                    st.info("標題已更新，現有逐字稿保留，可到腳本編輯頁提出修改。")
                d.title = chosen
                refresh(s)
    st.caption("到「腳本編輯」可手動調整標題、設定長度並生成逐字稿。")
