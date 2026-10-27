from pydantic import BaseModel, ConfigDict, Field
from core.ai.provider import Provider, instruction


class ScriptResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    opening: str = Field(min_length=1, max_length=2000)
    body: str = Field(min_length=1, max_length=6000)
    ending: str = Field(min_length=1, max_length=2000)

    def text(self) -> str:
        return "\n\n".join([self.opening, self.body, self.ending])


def generate_script(provider: Provider, topic: dict, title: str, seconds: int, config: dict) -> ScriptResult:
    if seconds not in (30, 45, 60) or not title.strip():
        raise ValueError("請先填寫標題並選擇30、45或60秒。")
    target = round(seconds * config.get("characters_per_second", 3.5))
    return provider.generate(instruction(config) +
        "撰寫可直接口播的完整逐字稿。開頭約3至5秒，主體分析原因及給建議，結尾簡短總結。"
        f"目標約{target}個中文字；依目標時長調整，無須精確秒數。不在正文加入段落標籤或舞台指示。",
        {"topic": topic, "title": title, "target_seconds": seconds}, ScriptResult)
