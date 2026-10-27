from uuid import UUID, uuid4
import streamlit as st
from core.storage.schemas import Draft


def persist(services):
    services.repo.save_draft(st.session_state.draft_id, st.session_state.draft)


def initialize(services):
    if "draft" not in st.session_state:
        token = st.query_params.get("draft", "")
        try:
            UUID(token)
        except (ValueError, TypeError, AttributeError):
            token = str(uuid4())
        draft = services.repo.load_draft(token)
        if draft and draft.selection:
            services.catalog.validate(draft.selection)
        st.session_state.draft_id = token
        st.session_state.draft = draft or Draft()
        st.session_state.sync_editor = True
        st.query_params["draft"] = token
        persist(services)
    if st.session_state.get("sync_editor"):
        d = st.session_state.draft
        for key in ("title", "script", "duration", "status"):
            st.session_state["edit_" + key] = getattr(d, key)
        st.session_state.sync_editor = False


def refresh(services):
    persist(services)
    st.session_state.sync_editor = True
    st.rerun()


def switch(services, draft: Draft, token: str | None = None):
    persist(services)
    st.session_state.draft_id = token or str(uuid4())
    st.query_params["draft"] = st.session_state.draft_id
    st.session_state.draft = draft
    refresh(services)


def edit_callback(services, field):
    setattr(st.session_state.draft, field, st.session_state["edit_" + field])
    persist(services)
