"""Tests for Stage 2 error index calculator."""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    parse_stage2_langflow_generation_result,
)
from app.services.stage2_index_calculator import (
    Stage2IndexCalculationCode,
    apply_server_error_indices,
    calculate_error_index_span,
)

FLAWED_RESPONSE = (
    "장영실은 정말 뛰어난 발명가였어요. "
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요. "
    "장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요."
)
ERROR_SENTENCE_1 = (
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요."
)
ERROR_SENTENCE_2 = (
    "장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요."
)


def test_calculate_index_for_single_occurrence() -> None:
    result = calculate_error_index_span(
        error_sentence=ERROR_SENTENCE_1,
        flawed_ai_response=FLAWED_RESPONSE,
    )

    assert result.is_success is True
    assert result.span is not None
    start = result.span.start_index
    end = result.span.end_index
    assert FLAWED_RESPONSE[start:end] == ERROR_SENTENCE_1


def test_calculate_index_not_found() -> None:
    result = calculate_error_index_span(
        error_sentence="존재하지 않는 문장",
        flawed_ai_response=FLAWED_RESPONSE,
    )

    assert result.is_success is False
    assert result.codes == (Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND,)


def test_calculate_index_ambiguous() -> None:
    flawed = "같은 문장입니다. 같은 문장입니다."
    result = calculate_error_index_span(
        error_sentence="같은 문장입니다.",
        flawed_ai_response=flawed,
    )

    assert result.is_success is False
    assert result.codes == (Stage2IndexCalculationCode.ERROR_SENTENCE_AMBIGUOUS,)


def test_apply_server_error_indices_to_baseline_fixture(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    langflow_result = stage2_langflow_baseline_fixture["langflow_result"]
    parsed = parse_stage2_langflow_generation_result(
        flawed_ai_response=langflow_result["flawed_ai_response"],
        raw_errors=langflow_result["generated_errors"],
    )

    application = apply_server_error_indices(parsed)

    assert application.applied is True
    assert application.codes == ()
    flawed = application.result.flawed_ai_response
    for error in application.result.generated_errors:
        assert error.start_index is not None
        assert error.end_index is not None
        assert error.start_index > 0 or error.end_index > 0
        assert flawed[error.start_index : error.end_index] == error.error_sentence


def test_apply_server_error_indices_ignores_llm_zero_indices() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=FLAWED_RESPONSE,
        generated_errors=[
            Stage2GeneratedErrorDraft.model_validate(
                {
                    "error_sentence": ERROR_SENTENCE_1,
                    "error_type": "RETRIEVAL_ERROR",
                    "correct_sentence": "correct",
                    "hallucination_reason": "reason",
                    "evidence_sentence": "evidence",
                    "start_index": 0,
                    "end_index": 0,
                }
            )
        ],
    )

    application = apply_server_error_indices(result)

    assert application.applied is True
    error = application.result.generated_errors[0]
    assert (error.start_index, error.end_index) != (0, 0)
    assert FLAWED_RESPONSE[error.start_index : error.end_index] == ERROR_SENTENCE_1


def test_apply_server_error_indices_fails_when_any_error_ambiguous() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=FLAWED_RESPONSE,
        generated_errors=[
            Stage2GeneratedErrorDraft.model_validate(
                {
                    "error_sentence": ERROR_SENTENCE_1,
                    "error_type": "RETRIEVAL_ERROR",
                    "correct_sentence": "correct",
                    "hallucination_reason": "reason",
                    "evidence_sentence": "evidence",
                }
            ),
            Stage2GeneratedErrorDraft.model_validate(
                {
                    "error_sentence": "없는 문장",
                    "error_type": "PERSONA_BIAS",
                    "correct_sentence": "correct",
                    "hallucination_reason": "reason",
                    "evidence_sentence": "evidence",
                }
            ),
        ],
    )

    application = apply_server_error_indices(result)

    assert application.applied is False
    assert Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND in application.codes
    assert application.result.generated_errors[0].start_index is None


@pytest.mark.parametrize(
    ("error_sentence", "expected_code"),
    [
        ("", Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND),
        ("   ", Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND),
    ],
)
def test_calculate_index_rejects_empty_sentence(
    error_sentence: str,
    expected_code: Stage2IndexCalculationCode,
) -> None:
    result = calculate_error_index_span(
        error_sentence=error_sentence,
        flawed_ai_response=FLAWED_RESPONSE,
    )
    assert expected_code in result.codes
