from pydantic import BaseModel, ConfigDict, Field
from core.ai.provider import Provider, instruction


class RevisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    script: str = Field(min_length=1, max_length=20000)
    explanation: str = Field(min_length=1, max_length=2000)


def revise(provider: Provider, topic: dict, title: str, script: str, seconds: int,
           history: list[dict], request: str, config: dict) -> RevisionResult:
    if not script.strip() or not request.strip():
        raise ValueError("請先輸入逐字稿及修改要求。")
    return provider.generate(instruction(config) +
        "根據目前全文、歷次對話及最新要求提出完整新版全文與簡短說明。"
        "保留未要求修改的段落。歷次提案可能被取消，始終以目前全文為準。"
        "回傳提案供使用者確認，不能聲稱已套用。",
        {"topic": topic, "title": title, "current_script": script, "target_seconds": seconds,
         "history": history, "request": request}, RevisionResult)
