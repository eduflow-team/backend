"""Stage 4 과제 API Request/Response 스키마 (Notion flat JSON)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


Difficulty = Literal["EASY", "NORMAL", "HARD"]


class Stage4AttemptsInfo(BaseModel):
    used_attempts: int
    remaining_attempts: int
    max_attempts: int


class Stage4LiteracyAxesScore(BaseModel):
    """Stage4가 산출하는 울산형 3축 (0~100)."""

    ethics: int
    critical: int
    collaboration: int


class Stage4EvaluationReport(BaseModel):
    clear_score: int
    efficiency_score: int
    analysis_score: int
    feedback: str
    literacy_axes: Stage4LiteracyAxesScore | None = None


class Stage4CreateRequest(BaseModel):
    class_id: int
    title: str = Field(..., min_length=1, max_length=120)
    mission: str = Field(..., min_length=1)
    secret_key: str = Field(..., min_length=1, max_length=100)
    max_attempts: int = Field(..., ge=1, le=30)
    guideline: str = Field(..., min_length=1)

    @field_validator("title", "mission", "guideline", "secret_key")
    @classmethod
    def strip_all(cls, v: str) -> str:
        return (v or "").strip()


class Stage4DifficultyAssignment(BaseModel):
    assignment_id: int
    difficulty: Difficulty


class Stage4CreateResponse(BaseModel):
    set_id: int
    title: str
    mission: str
    max_attempts: int
    assignments: list[Stage4DifficultyAssignment]


class Stage4AttackLogItem(BaseModel):
    attempt_no: int
    attack_prompt: str
    ai_response: str
    attack_success: bool
    created_at: datetime | None = None


class Stage4HintItem(BaseModel):
    level: int
    text: str
    unlocked: bool


class Stage4DifficultyHints(BaseModel):
    difficulty: Difficulty
    hint_level: int
    hints: list[Stage4HintItem]


class Stage4DifficultyScoreItem(BaseModel):
    assignment_id: int
    difficulty: Difficulty
    unlocked: bool
    is_cleared: bool


class Stage4SetScore(BaseModel):
    set_id: int
    overall_score: int
    is_passed: bool
    cleared_count: int
    can_submit_report: bool
    report_submitted: bool
    submitted_report: Stage4Report | None = None
    evaluation_report: Stage4EvaluationReport | None = None
    current_score: int | None = None
    difficulties: list[Stage4DifficultyScoreItem]
    difficulty_hints: list[Stage4DifficultyHints] = Field(default_factory=list)


class Stage4AssignmentDetailResponse(BaseModel):
    assignment_id: int
    title: str
    mission: str
    guideline: str
    difficulty: Difficulty
    unlocked: bool
    status: str
    is_cleared: bool
    attempts: Stage4AttemptsInfo
    attack_logs: list[Stage4AttackLogItem]
    hint_level: int = 0
    hint: str | None = None
    hints: list[Stage4HintItem] = Field(default_factory=list)
    set: Stage4SetScore


class Stage4ChatRequest(BaseModel):
    attack_prompt: str = Field(..., min_length=1)

    @field_validator("attack_prompt")
    @classmethod
    def strip_prompt(cls, v: str) -> str:
        return v.strip()


class Stage4ChatResponse(BaseModel):
    ai_response: str
    attack_success: bool
    is_cleared: bool
    hint_level: int
    hint: str | None
    attempts: Stage4AttemptsInfo


class Stage4Report(BaseModel):
    successful_attacks: str = Field(..., min_length=1)
    failed_attacks: str = Field(..., min_length=1)
    why_breached: str = Field(..., min_length=1)
    defense_ideas: str = Field(..., min_length=1)

    @field_validator(
        "successful_attacks",
        "failed_attacks",
        "why_breached",
        "defense_ideas",
    )
    @classmethod
    def strip_report_fields(cls, v: str) -> str:
        return (v or "").strip()


class Stage4SubmitRequest(BaseModel):
    report: Stage4Report


class Stage4SubmitResponse(BaseModel):
    current_score: int
    is_passed: bool
    evaluation_report: Stage4EvaluationReport
    attempts: Stage4AttemptsInfo
    set: Stage4SetScore

