"""Stage 2 Langflow 생성 결과 내부 스키마.

외부 API(`app.schemas.stage2`)와 분리된 백엔드 ↔ Langflow 계약 타입.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.schemas.stage2 import ALLOWED_HALLUCINATION_TYPES

ALLOWED_RETRIEVAL_SOURCES = frozenset({"SAME_DOCUMENT", "SYNTHETIC"})


class Stage2GeneratedErrorDraft(BaseModel):
    """Langflow가 반환하는 단일 오류 항목 (DB/API 저장 전 내부 표현)."""

    model_config = ConfigDict(extra="ignore")

    error_sentence: str = Field(..., min_length=1)
    error_type: str
    correct_sentence: str = Field(..., min_length=1)
    hallucination_reason: str = Field(..., min_length=1)
    evidence_sentence: str = Field(..., min_length=1)
    retrieval_source: str | None = None
    retrieved_context: str | None = None
    # LLM이 줄 수 있으나 step 4에서 서버가 재계산한다.
    start_index: int | None = None
    end_index: int | None = None

    @field_validator(
        "error_sentence",
        "correct_sentence",
        "hallucination_reason",
        "evidence_sentence",
        "retrieved_context",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("error_type")
    @classmethod
    def validate_error_type(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in ALLOWED_HALLUCINATION_TYPES:
            raise ValueError("invalid error_type")
        return normalized

    @field_validator("retrieval_source")
    @classmethod
    def validate_retrieval_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in ALLOWED_RETRIEVAL_SOURCES:
            raise ValueError("invalid retrieval_source")
        return normalized


class Stage2LangflowGenerationResult(BaseModel):
    """Langflow Stage 2 생성 호출의 파싱·검증된 내부 결과."""

    flawed_ai_response: str = Field(..., min_length=1)
    generated_errors: list[Stage2GeneratedErrorDraft]

    @field_validator("flawed_ai_response", mode="before")
    @classmethod
    def strip_flawed_response(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("flawed_ai_response must not be empty")
        return stripped


def parse_stage2_generated_errors(
    raw_errors: list[Any],
) -> list[Stage2GeneratedErrorDraft]:
    """Langflow JSON 배열을 내부 오류 draft 목록으로 변환한다."""
    return [Stage2GeneratedErrorDraft.model_validate(item) for item in raw_errors]


def parse_stage2_langflow_generation_result(
    *,
    flawed_ai_response: str,
    raw_errors: list[Any],
) -> Stage2LangflowGenerationResult:
    """Langflow 출력을 내부 생성 결과 모델로 변환한다."""
    return Stage2LangflowGenerationResult(
        flawed_ai_response=flawed_ai_response,
        generated_errors=parse_stage2_generated_errors(raw_errors),
    )


__all__ = [
    "ALLOWED_RETRIEVAL_SOURCES",
    "Stage2GeneratedErrorDraft",
    "Stage2LangflowGenerationResult",
    "ValidationError",
    "parse_stage2_generated_errors",
    "parse_stage2_langflow_generation_result",
]
