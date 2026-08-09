"""Stage 2 Langflow 생성 결과를 교사 요청값에 맞게 정렬한다."""

from __future__ import annotations

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)


def align_stage2_generation_result(
    result: Stage2LangflowGenerationResult,
    *,
    hallucination_types: list[str],
    expected_error_count: int,
) -> Stage2LangflowGenerationResult:
    """오류 개수·유형을 교사 입력 기준으로 보정한다.

  Planner/Formatter가 개수·유형을 어긋내도 검증 전에 1차 정렬한다.
  오류 항목 자체가 부족한 경우는 그대로 둔다.
    """
    allowed_types = [value.strip().upper() for value in hallucination_types if value.strip()]
    errors = list(result.generated_errors)

    if expected_error_count > 0 and len(errors) > expected_error_count:
        errors = errors[:expected_error_count]

    if allowed_types:
        aligned: list[Stage2GeneratedErrorDraft] = []
        for index, error in enumerate(errors):
            assigned_type = (
                allowed_types[index]
                if index < len(allowed_types)
                else error.error_type
            )
            aligned.append(
                error.model_copy(update={"error_type": assigned_type}),
            )
        errors = aligned

    return result.model_copy(update={"generated_errors": errors})
