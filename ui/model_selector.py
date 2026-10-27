"""Model preference UI, independent of Streamlit's cached settings module."""
import streamlit as st
from core.ai.provider import GeminiProvider


def render_model_selector(provider) -> None:
    if not isinstance(provider, GeminiProvider):
        return
    # A running cloud process may retain the provider class from before the
    # selector was added. Its configured models are still the full allowlist.
    if not hasattr(provider, 'allowed_models'):
        provider.allowed_models = tuple(provider.models)
    automatic = '自動備援（預設）'
    options = [automatic, *provider.allowed_models]
    if st.session_state.get('ai_model_choice', automatic) not in options:
        st.session_state.ai_model_choice = automatic
    selected = st.selectbox('AI 模型', options, key='ai_model_choice')
    fallback = True
    if selected != automatic:
        fallback = st.checkbox('失敗時切換其他備援模型', value=True, key='ai_manual_fallback')
    model = None if selected == automatic else selected
    if hasattr(provider, 'prefer_model'):
        provider.prefer_model(model, fallback=fallback)
    else:
        # Use only the existing public request fields on a cached older class.
        provider.models = provider.allowed_models if model is None else (
            (model, *(m for m in provider.allowed_models if m != model)) if fallback else (model,))
        provider.model = provider.models[0]
        provider.last_model = None
    st.caption('本次呼叫順序：' + ' → '.join(provider.models))
    st.caption('切換模型只影響之後的生成，不會立即呼叫AI或更改既有稿件。')
