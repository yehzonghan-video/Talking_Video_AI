from typing import Literal
from pydantic import Field, model_validator
from core.storage.schemas import StrictModel, identifier, now


class Interval(StrictModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('結束時間必須晚於開始時間。')
        return self


class MediaInfo(StrictModel):
    duration: float = Field(gt=0, le=900, allow_inf_nan=False)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    display_width: int = Field(gt=0)
    display_height: int = Field(gt=0)
    rotation: int = 0
    fps: float = Field(gt=0, le=1000, allow_inf_nan=False)
    size: int = Field(gt=0)
    format_name: str
    video_codec: str
    audio_codec: str | None = None
    audio_start: float | None = None
    video_start: float = 0
    video_duration: float | None = None
    audio_duration: float | None = None


class Word(Interval):
    text: str


class Segment(Interval):
    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=10000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[Word] = Field(default_factory=list)


class Transcript(StrictModel):
    provider: str
    model: str
    language: str = 'zh-TW'
    timing: Literal['acoustic-alignment', 'unverified'] = 'unverified'
    segments: list[Segment]


class Decision(Interval):
    id: str = Field(default_factory=identifier)
    kind: Literal['silence', 'repetition', 'retake', 'semantic', 'manual']
    action: Literal['remove', 'review'] = 'review'
    reason: str = Field(min_length=1, max_length=2000)
    confidence: float | None = None  # No calibrated edit confidence is available.
    requires_review: bool = True
    selected: bool = False
    confirmed: bool = False
    segment_ids: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def no_fake_confidence(self):
        if self.confidence is not None:
            raise ValueError('本版不提供未校準的剪輯信心分數。')
        return self


class Timeline(StrictModel):
    number: int = Field(ge=1)
    duration: float = Field(gt=0, le=900, allow_inf_nan=False)
    keep_segments: list[Interval] = Field(min_length=1)
    decisions: list[Decision] = Field(default_factory=list)
    note: str
    created_at: str = Field(default_factory=now)


class Match(StrictModel):
    script_index: int = Field(ge=0)
    script_text: str
    segment_ids: list[str] = Field(default_factory=list)
    status: Literal['matched', 'paraphrase', 'needs_review', 'missing']
    reason: str


class AnalysisSettings(StrictModel):
    min_pause: float = Field(default=1.5, ge=0.5, le=10)
    retain_pause: float = Field(default=0.4, ge=0.3, le=1.5)
    noise_db: int = Field(default=-35, ge=-60, le=-15)
    padding: float = Field(default=0.15, ge=0.08, le=0.5)

    @model_validator(mode='after')
    def sensible(self):
        if self.retain_pause >= self.min_pause:
            raise ValueError('保留停頓必須短於偵測門檻。')
        return self


class VideoProject(StrictModel):
    id: str = Field(default_factory=identifier, pattern=r'^[0-9a-f-]{36}$')
    script_id: str
    title: str
    script_snapshot: str
    script_version: int
    original_name: str
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_suffix: Literal['.mp4', '.mov']
    media: MediaInfo
    transcript: Transcript | None = None
    silences: list[Interval] = Field(default_factory=list)
    matches: list[Match] = Field(default_factory=list)
    suggestions: list[Decision] = Field(default_factory=list)
    timelines: list[Timeline] = Field(min_length=1)
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    analysis_signature: str = ''
    analysis_note: str = ''
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    revision: int = Field(default=0, ge=0)
    export_status: Literal['未輸出', '已輸出'] = '未輸出'
    output_key: str | None = None
    output_timeline: int | None = None

    @model_validator(mode='after')
    def timeline_versions(self):
        if [t.number for t in self.timelines] != list(range(1, len(self.timelines) + 1)):
            raise ValueError('剪輯版本編號不連續。')
        return self
