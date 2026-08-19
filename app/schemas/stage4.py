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


class Stage4EvaluationReport(BaseModel):
    clear_score: int
    efficiency_score: int
    analysis_score: int
    feedback: str


class Stage4CreateRequest(BaseModel):
    class_id: int
    mission: str = Field(..., min_length=1)
    secret_key: str = Field(..., min_length=1, max_length=100)
    difficulty: Difficulty
    max_attempts: int = Field(..., ge=1, le=30)
    guideline: str = Field(..., min_length=1)

    @field_validator("mission", "guideline", "secret_key")
    @classmethod
    def strip_all(cls, v: str) -> str:
        return (v or "").strip()


class Stage4CreateResponse(BaseModel):
    assignment_id: int
    title: str
    mission: str
    difficulty: Difficulty
    max_attempts: int


class Stage4AttackLogItem(BaseModel):
    attempt_no: int
    attack_prompt: str
    ai_response: str
    attack_success: bool
    created_at: datetime | None = None


class Stage4AssignmentDetailResponse(BaseModel):
    assignment_id: int
    title: str
    mission: str
    guideline: str
    difficulty: Difficulty
    status: str
    is_cleared: bool
    can_submit_report: bool
    attempts: Stage4AttemptsInfo
    attack_logs: list[Stage4AttackLogItem]


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

