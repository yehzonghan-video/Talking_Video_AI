from pydantic import Field, model_validator
from typing import Literal
from core.storage.schemas import StrictModel, identifier


class Span(StrictModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered(self):
        if self.start >= self.end:
            raise ValueError('字幕結束時間必須晚於開始時間。')
        return self


class Atom(Span):
    text: str = Field(min_length=1, max_length=10000)


class SourceCaption(StrictModel):
    id: str = Field(default_factory=identifier)
    spans: list[Span] = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    highlights: list[str] = Field(default_factory=list, max_length=30)
    atoms: list[Atom] = Field(default_factory=list, max_length=2000)
    manual: bool = False
    review_reason: str = ''
    correction_ref: str = ''


class ScriptCorrection(StrictModel):
    id: str
    cue_id: str
    original: str
    proposed: str
    reference: str
    status: Literal['auto', 'review', 'keep']
    decision: Literal['accepted', 'rejected', 'pending']
    reason: str


class CaptionStyle(StrictModel):
    preset: Literal['basic', 'emphasis'] = 'basic'
    font_size: int = Field(default=52, ge=24, le=96)
    bottom_percent: float = Field(default=12, ge=5, le=35, allow_inf_nan=False)


class SubtitleTrack(StrictModel):
    cues: list[SourceCaption] = Field(default_factory=list, max_length=3000)
    source_signature: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision: int = Field(default=1, ge=1)
    enabled: bool = True
    style: CaptionStyle = Field(default_factory=CaptionStyle)
    note: str = ''
    original_cues: list[SourceCaption] = Field(default_factory=list, max_length=3000)
    corrections: list[ScriptCorrection] = Field(default_factory=list, max_length=3000)
    text_source: Literal['asr', 'script'] = 'asr'
    script_signature: str = ''
    unaligned: list[str] = Field(default_factory=list, max_length=3000)


class OutputCaption(Span):
    id: str
    text: str = Field(min_length=1, max_length=10000)
    highlights: list[str] = Field(default_factory=list)
    source_spans: list[Span]
    needs_review: bool = False
    review_reason: str = ''
