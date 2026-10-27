from pydantic import BaseModel, ConfigDict, Field, field_validator
from core.ai.provider import Provider, instruction, AIError


class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
    b: str
    c: str


class TitleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasonable: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=1000)
    alternatives: list[Alternative] = Field(max_length=3)
    titles: list[str] = Field(min_length=5, max_length=5)

    @field_validator("titles")
    @classmethod
    def distinct(cls, values):
        values = [s.strip() for s in values]
        if any(not s or len(s) > 120 for s in values) or len(set(values)) != 5:
            raise ValueError("需要五個不同的非空標題。")
        return values

    @field_validator("alternatives")
    @classmethod
    def alternatives_unique(cls, values):
        if len({(v.a, v.b, v.c) for v in values}) != len(values):
            raise ValueError("替代選題不可重複。")
        return values


def generate_titles(provider: Provider, topic: dict, catalog_data: dict, config: dict) -> TitleResult:
    result = provider.generate(instruction(config) +
        "先評估業務與客群關聯、角度是否適合、知識價值、30至60秒單人口播可行性，及是否必須虛構案例。"
        "若不合理，說明簡短原因並建議1至3個有效替代組合。無論判斷結果都生成五個簡短、有差異、不誇張的標題。",
        {"topic": topic, "available_categories": catalog_data}, TitleResult)
    if not result.reasonable and not result.alternatives:
        raise AIError("AI 未提供替代選題，請重試。原有內容已保留。")
    return result
