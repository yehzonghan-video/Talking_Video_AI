from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, model_validator

STATUSES = ["企劃中", "待拍攝", "已拍攝", "已完成", "已發布"]
Status = Literal["企劃中", "待拍攝", "已拍攝", "已完成", "已發布"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identifier() -> str:
    return str(uuid4())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Version(StrictModel):
    number: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=200)
    script: str = Field(min_length=1, max_length=20000)
    duration: Literal[30, 45, 60]
    note: str = Field(min_length=1, max_length=2000)
    created_at: str = Field(default_factory=now)


class ChatTurn(StrictModel):
    request: str = Field(min_length=1, max_length=5000)
    proposal: str = Field(min_length=1, max_length=20000)
    explanation: str = Field(min_length=1, max_length=2000)
    outcome: Literal["待確認", "已套用", "已取消"]


class Project(StrictModel):
    id: str = Field(default_factory=identifier, pattern=r"^[0-9a-f-]{36}$")
    combination_id: str
    selection: dict[str, str]
    title: str = Field(min_length=1, max_length=200)
    script: str = Field(min_length=1, max_length=20000)
    duration: Literal[30, 45, 60] = 45
    status: Status = "企劃中"
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    versions: list[Version] = Field(min_length=1)
    history: list[ChatTurn] = Field(default_factory=list)
    revision: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent(self):
        if set(self.selection) != set("abc") or self.combination_id != "-".join(self.selection[d] for d in "abc"):
            raise ValueError("組合 ID 與分類不一致。")
        if not self.title.strip() or not self.script.strip():
            raise ValueError("標題與逐字稿不可空白。")
        if [v.number for v in self.versions] != list(range(1, len(self.versions) + 1)):
            raise ValueError("版本編號不連續。")
        last = self.versions[-1]
        if (last.title, last.script, last.duration) != (self.title, self.script, self.duration):
            raise ValueError("最新版本與腳本內容不一致。")
        for stamp in [self.created_at, self.updated_at] + [v.created_at for v in self.versions]:
            parsed = datetime.fromisoformat(stamp)
            if parsed.tzinfo is None:
                raise ValueError("時間必須包含時區。")
        return self


class Pending(StrictModel):
    base_title: str
    base_script: str
    base_duration: Literal[30, 45, 60]
    script: str = Field(min_length=1, max_length=20000)
    request: str = Field(min_length=1, max_length=5000)
    explanation: str = Field(min_length=1, max_length=2000)


class Draft(StrictModel):
    project_id: str = Field(default_factory=identifier, pattern=r"^[0-9a-f-]{36}$")
    selection: dict[str, str] | None = None
    title: str = Field(default="", max_length=200)
    script: str = Field(default="", max_length=20000)
    duration: Literal[30, 45, 60] = 45
    status: Status = "企劃中"
    created_at: str = Field(default_factory=now)
    versions: list[Version] = Field(default_factory=list)
    history: list[ChatTurn] = Field(default_factory=list)
    pending: Pending | None = None
    title_result: dict | None = None
    saved_revision: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_pending(self):
        if self.pending and (not self.history or self.history[-1].outcome != "待確認"):
            raise ValueError("修改提案與對話紀錄不一致。")
        if [v.number for v in self.versions] != list(range(1, len(self.versions) + 1)):
            raise ValueError("草稿版本編號不連續。")
        return self


class Backup(StrictModel):
    format: Literal["talking-video-ai"] = "talking-video-ai"
    schema_version: Literal[1] = 1
    exported_at: str = Field(default_factory=now)
    projects: list[Project]
    used_combinations: list[str] = Field(default_factory=list)


def json_text(value: BaseModel) -> str:
    return value.model_dump_json(indent=2)
