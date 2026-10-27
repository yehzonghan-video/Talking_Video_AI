from typing import Literal
import unicodedata
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from core.ai.provider import Provider, instruction


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    c: str


class TitleIdea(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=1000,
        description="這個標題對應的具體生活情境、使用需求或問題，以及要分享的知識重點；須與其他選題不同。")


def topic_key(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


class TitleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["適合", "可延伸", "不建議"]
    reason: str = Field(min_length=1, max_length=1000)
    alternatives: list[Alternative] = Field(max_length=3)
    titles: list[TitleIdea] = Field(max_length=5)

    @model_validator(mode="after")
    def valid_topics(self):
        if self.status == "不建議":
            if self.titles or not self.alternatives:
                raise ValueError("不建議時不得捏造標題，且須提供1至3個替代組合。")
        elif not self.titles or self.alternatives:
            raise ValueError("適合及可延伸的組合須提供1至5個標題，不需替代組合。")
        for field in ("title", "topic"):
            keys = [topic_key(getattr(idea, field)) for idea in self.titles]
            if any(not key for key in keys) or len(set(keys)) != len(keys):
                raise ValueError("每個標題與具體選題均須非空且不同，不能重複湊數。")
        return self

    @field_validator("alternatives")
    @classmethod
    def alternatives_unique(cls, values):
        if len({(v.a, v.b, v.c) for v in values}) != len(values):
            raise ValueError("替代選題不可重複。")
        return values


def generate_titles(provider: Provider, topic: dict, catalog_data: dict, config: dict) -> TitleResult:
    return provider.generate(instruction(config) +
        "先積極探索ABC組合能成立的真實生活情境、使用需求及具體問題，不可只按分類表面關聯否定。"
        "只要至少找到一個有實際知識價值、適合30至60秒單人口播且不需虛構事實的切入點，就應生成標題。"
        "status分為：適合（關聯直接且有價值）、可延伸（關聯較弱，但有可信的情境或合理需求）、不建議。"
        "適合與可延伸都正常提供1至5個標題，數量取決於能成立的不同具體選題，絕不強制湊滿五個。"
        "先合併實質相同的選題；每個title都要對應不同的topic，說清楚情境、問題及知識重點，不能只是同一內容換句話說。"
        "標題須簡短、自然且不誇張。選題少不代表組合不合理，只有一題也可以標示適合或可延伸。"
        "只有完全找不到可信且有價值的切入點時才標為不建議，titles為空，提供1至3個有效替代組合；"
        "其他狀態alternatives為空。reason簡短說明成立情境與價值，或為何完全無法成立。",
        {"topic": topic, "available_categories": catalog_data}, TitleResult)
