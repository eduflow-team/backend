"""Tests for Stage 2 generation alignment."""

from __future__ import annotations

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)
from app.services.stage2_generation_align import align_stage2_generation_result


def _error(error_type: str) -> Stage2GeneratedErrorDraft:
    return Stage2GeneratedErrorDraft(
        error_sentence=f"{error_type} sentence",
        error_type=error_type,
        correct_sentence="correct",
        hallucination_reason="reason",
        evidence_sentence="evidence",
    )


def test_align_trims_extra_errors() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response="answer",
        generated_errors=[
            _error("PERSONA_BIAS"),
            _error("INFORMATION_FABRICATION"),
            _error("RETRIEVAL_ERROR"),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["PERSONA_BIAS", "INFORMATION_FABRICATION"],
        expected_error_count=2,
    )

    assert len(aligned.generated_errors) == 2
    assert aligned.generated_errors[0].error_type == "PERSONA_BIAS"
    assert aligned.generated_errors[1].error_type == "INFORMATION_FABRICATION"


def test_align_remaps_error_types_in_request_order() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response="answer",
        generated_errors=[
            _error("RETRIEVAL_ERROR"),
            _error("PERSONA_BIAS"),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["PERSONA_BIAS", "INFORMATION_FABRICATION"],
        expected_error_count=2,
    )

    assert aligned.generated_errors[0].error_type == "PERSONA_BIAS"
    assert aligned.generated_errors[1].error_type == "INFORMATION_FABRICATION"
