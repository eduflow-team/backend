"""Stage 2 Langflow 생성 결과 내부 스키마.

외부 API(`app.schemas.stage2`)와 분리된 백엔드 ↔ Langflow 계약 타입.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.schemas.stage2 import ALLOWED_HALLUCINATION_TYPES

ALLOWED_RETRIEVAL_SOURCES = frozenset({"SAME_DOCUMENT", "SYNTHETIC"})


class Stage2RetrievalCandidate(BaseModel):
    """Langflow Planner에 전달하는 동일 PDF 청크 후보."""

    chunk_id: str = Field(..., min_length=1)
    source_index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    selection_bucket: Literal["TOP_RELEVANCE", "DIVERSE_CONTEXT"]


class Stage2RetrievalInput(BaseModel):
    """동일 문서 우선, 부적합 시 synthetic fallback을 허용하는 입력 계약."""

    strategy: Literal["SAME_DOCUMENT_THEN_SYNTHETIC"] = (
        "SAME_DOCUMENT_THEN_SYNTHETIC"
    )
    candidate_chunks: list[Stage2RetrievalCandidate]
    synthetic_fallback_allowed: bool = True


class Stage2GenerationMetadata(BaseModel):
    """Stage 2 생성 파이프라인 감사·재현용 내부 메타데이터 (외부 API 미노출)."""

    model_config = ConfigDict(extra="ignore")

    flow_version: str = Field(..., min_length=1)
    generation_attempts: int = Field(..., ge=1)
    retrieval_source: str | None = None
    retrieved_context: str | None = None
    validation_codes: list[str] = Field(default_factory=list)
    candidate_chunk_ids: list[str] = Field(default_factory=list)
    document_excerpt_applied: bool = False
    source_char_count: int | None = Field(default=None, ge=0)
    generation_char_count: int | None = Field(default=None, ge=0)

    @field_validator("retrieval_source")
    @classmethod
    def validate_retrieval_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in ALLOWED_RETRIEVAL_SOURCES:
            raise ValueError("invalid retrieval_source")
        return normalized

    @field_validator("retrieved_context", mode="before")
    @classmethod
    def strip_retrieved_context(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


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


def parse_stage2_generation_metadata(
    raw: dict[str, Any] | None,
) -> Stage2GenerationMetadata | None:
    """DB JSON 컬럼 값을 내부 메타데이터 모델로 변환한다."""
    if raw is None:
        return None
    return Stage2GenerationMetadata.model_validate(raw)


def dump_stage2_generation_metadata(
    metadata: Stage2GenerationMetadata,
) -> dict[str, Any]:
    """내부 메타데이터를 DB JSON 컬럼에 저장 가능한 dict로 변환한다."""
    return metadata.model_dump(mode="json")


__all__ = [
    "ALLOWED_RETRIEVAL_SOURCES",
    "Stage2GeneratedErrorDraft",
    "Stage2GenerationMetadata",
    "Stage2LangflowGenerationResult",
    "Stage2RetrievalCandidate",
    "Stage2RetrievalInput",
    "ValidationError",
    "dump_stage2_generation_metadata",
    "parse_stage2_generated_errors",
    "parse_stage2_generation_metadata",
    "parse_stage2_langflow_generation_result",
]
