import json
import os
from dataclasses import dataclass
from pathlib import Path
import streamlit as st
from core.ai.provider import GeminiProvider
from core.topics.topic_manager import Catalog
from core.storage.project_manager import SQLiteRepository, Repository

ROOT = Path(__file__).resolve().parents[1]


def setting(name: str, default: str = "") -> str:
    try:
        secret = st.secrets.get(name)
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        secret = None
    return str(secret or os.environ.get(name, default))


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
    return Services(Catalog(categories), SQLiteRepository(setting("DATA_PATH", str(ROOT / "data" / "talking_video.db"))),
                    GeminiProvider(setting("GEMINI_API_KEY") or setting("GOOGLE_API_KEY"), setting("GEMINI_MODEL", "gemini-3.5-flash")), config)
