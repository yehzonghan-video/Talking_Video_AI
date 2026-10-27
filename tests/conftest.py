from pathlib import Path
import pytest
from core.topics.topic_manager import Catalog
from core.storage.project_manager import SQLiteRepository
from core.storage.schemas import Draft
from core.workflow import checkpoint

ROOT = Path(__file__).resolve().parents[1]


class FakeProvider:
    api_key = "test-only"
    model = "fake"

    def __init__(self):
        self.calls = []
        self.failure = None

    def generate(self, instruction, payload, schema):
        self.calls.append((instruction, payload, schema))
        if self.failure:
            raise self.failure
        name = schema.__name__
        if name == "TitleResult":
            raw = dict(reasonable=True, reason="可以提供具體且實用的知識。", alternatives=[],
                       titles=["裝潢前先想清楚需求", "新家的預算怎麼安排", "動線順了生活更方便", "交屋後先別急著動工", "裝修前容易忽略的小細節"])
        elif name == "ScriptResult":
            raw = dict(opening="準備裝潢，卻不知道從哪開始？", body=f"先整理生活需求，再與設計師討論動線。這是{payload['target_seconds']}秒的測試逐字稿。", ending="需求清楚，規劃就更有方向。")
        else:
            raw = dict(script=payload["current_script"] + "\n\n修改：" + payload["request"], explanation="已依照要求修改，其他段落保留。")
        return schema.model_validate(raw)


@pytest.fixture
def catalog():
    return Catalog(ROOT / "categories.json")


@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(tmp_path / "test.db")


@pytest.fixture
def draft():
    d = Draft(selection=dict(a="A01", b="B01", c="C03"), title="裝潢前先想清楚需求", script="開頭。\n\n主體內容。\n\n結尾。")
    checkpoint(d, "AI 初稿")
    return d


@pytest.fixture
def fake():
    return FakeProvider()
