"""Tests for Stage 2 generation observability logging."""

from __future__ import annotations

import logging

import pytest

from app.schemas.stage2_generation import Stage2GeneratedErrorDraft
from app.services.stage2_generation_logging import (
    log_stage2_generation_attempt,
    log_stage2_generation_failed,
    log_stage2_generation_started,
    log_stage2_generation_succeeded,
    summarize_error_type_counts,
)


def test_summarize_error_type_counts() -> None:
    errors = [
        Stage2GeneratedErrorDraft.model_validate(
            {
                "error_sentence": "오류 A",
                "error_type": "RETRIEVAL_ERROR",
                "correct_sentence": "정답 A",
                "hallucination_reason": "이유 A",
                "evidence_sentence": "근거 A",
                "retrieved_context": "context",
            }
        ),
        Stage2GeneratedErrorDraft.model_validate(
            {
                "error_sentence": "오류 B",
                "error_type": "PERSONA_BIAS",
                "correct_sentence": "정답 B",
                "hallucination_reason": "이유 B",
                "evidence_sentence": "근거 B",
            }
        ),
        Stage2GeneratedErrorDraft.model_validate(
            {
                "error_sentence": "오류 C",
                "error_type": "PERSONA_BIAS",
                "correct_sentence": "정답 C",
                "hallucination_reason": "이유 C",
                "evidence_sentence": "근거 C",
            }
        ),
    ]

    assert summarize_error_type_counts(errors) == {
        "RETRIEVAL_ERROR": 1,
        "PERSONA_BIAS": 2,
    }


def test_generation_logs_do_not_include_document_body(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    log_stage2_generation_started(
        teacher_user_id=7,
        expected_error_count=2,
        hallucination_types=["PERSONA_BIAS"],
        filename="lesson.pdf",
    )
    log_stage2_generation_attempt(
        teacher_user_id=7,
        attempt=1,
        max_attempts=2,
        duration_ms=1532.4,
        failure_codes=("ERROR_COUNT_MISMATCH",),
        will_retry=True,
    )
    log_stage2_generation_succeeded(
        teacher_user_id=7,
        assignment_id=42,
        generation_attempts=2,
        error_type_counts={"PERSONA_BIAS": 1},
    )
    log_stage2_generation_failed(
        teacher_user_id=7,
        generation_attempts=2,
        failure_codes=("ERROR_SENTENCE_NOT_FOUND",),
    )

    combined = "\n".join(record.message for record in caplog.records)
    assert "teacher_user_id=7" in combined
    assert "assignment_id=42" in combined
    assert "duration_ms=1532.4" in combined
    assert "failure_codes=ERROR_COUNT_MISMATCH" in combined
    assert "error_type_counts=" in combined
    assert "lesson.pdf" in combined
    assert "장영실" not in combined
    assert "persona" not in combined.lower() or "persona_bias" in combined.lower()
