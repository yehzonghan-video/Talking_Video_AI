import json
import os
from dataclasses import dataclass
from pathlib import Path
import streamlit as st
from core.ai.provider import GeminiProvider, AIError, DEFAULT_MODELS, model_list, configure_call_logging
from core.topics.topic_manager import Catalog
from core.storage.project_manager import SQLiteRepository, Repository

ROOT = Path(__file__).resolve().parents[1]


def setting_value(name: str, default=None):
    try:
        secret = st.secrets.get(name)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        secret = None
    return secret if secret is not None else os.environ.get(name, default)


def setting(name: str, default: str = "") -> str:
    value = setting_value(name)
    return str(os.environ.get(name, default) if value is None or value == '' else value)


def configured_models() -> tuple[str, ...]:
    explicit = setting_value('GEMINI_MODELS')
    if explicit is not None:
        return model_list(explicit)
    return model_list([setting('GEMINI_MODEL', DEFAULT_MODELS[0]), *DEFAULT_MODELS[1:]])


def ai_provider() -> GeminiProvider:
    try:
        return GeminiProvider(setting('GEMINI_API_KEY') or setting('GOOGLE_API_KEY'), models=configured_models(),
            max_retries=int(setting('GEMINI_MAX_RETRIES', '2')),
            initial_delay=float(setting('GEMINI_RETRY_INITIAL_DELAY', '1')),
            max_delay=float(setting('GEMINI_RETRY_MAX_DELAY', '8')),
            request_timeout=float(setting('GEMINI_REQUEST_TIMEOUT', '60')),
            max_elapsed=float(setting('GEMINI_MAX_ELAPSED', '180')))
    except (ValueError, TypeError):
        raise AIError('Gemini模型清單或重試參數設定無效，請由管理者檢查 Secrets／環境變數。') from None


def render_model_selector(provider) -> None:
    if not isinstance(provider, GeminiProvider):
        return
    automatic = '自動備援（預設）'
    options = [automatic, *provider.allowed_models]
    if st.session_state.get('ai_model_choice', automatic) not in options:
        st.session_state.ai_model_choice = automatic
    selected = st.selectbox('AI 模型', options, key='ai_model_choice')
    fallback = True
    if selected != automatic:
        fallback = st.checkbox('失敗時切換其他備援模型', value=True, key='ai_manual_fallback')
    provider.prefer_model(None if selected == automatic else selected, fallback=fallback)
    st.caption('本次呼叫順序：' + ' → '.join(provider.models))
    st.caption('切換模型只影響之後的生成，不會立即呼叫AI或更改既有稿件。')


@dataclass
class Services:
    catalog: Catalog
    repo: Repository
    provider: GeminiProvider
    config: dict


def services() -> Services:
    industry = Path(setting("INDUSTRY_DIR", str(ROOT / "industries" / "interior_design")))
    preferred = industry / "categories.json"
    if preferred.exists():
        categories = preferred
    elif (ROOT / "categories.json").exists():
        categories = ROOT / "categories.json"
    else:
        found = [p for p in ROOT.rglob("categories.json") if not any(part.startswith(".") for part in p.relative_to(ROOT).parts)]
        if len(found) != 1:
            raise ValueError("找不到唯一的 categories.json，請由管理者指定 INDUSTRY_DIR。")
        categories = found[0]
    config = json.loads((industry / "prompt_config.json").read_text(encoding="utf-8"))
    database = Path(setting('DATA_PATH', str(ROOT / 'data/talking_video.db')))
    configure_call_logging(database.parent / 'logs/gemini_calls.jsonl')
    return Services(Catalog(categories), SQLiteRepository(database), ai_provider(), config)
