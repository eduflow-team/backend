"""Tests for Stage 2 E2E response validation helpers."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.stage2_response_validation import (
    Stage2E2EValidationError,
    validate_generated_error_item,
    validate_stage2_create_response,
)

DOCUMENT_TEXT = (
    "장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.\n"
    "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다."
)
FLAWED = (
    "장영실은 정말 뛰어난 발명가였어요. "
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요. "
    "장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요."
)
ALLOWED_TYPES = {"RETRIEVAL_ERROR", "PERSONA_BIAS"}


def _error_item(**overrides: Any) -> dict[str, Any]:
    sentence = (
        "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요."
    )
    start = FLAWED.find(sentence)
    base = {
        "answer_id": 1,
        "error_sentence": sentence,
        "error_type": "RETRIEVAL_ERROR",
        "start_index": start,
        "end_index": start + len(sentence),
        "correct_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
        "hallucination_reason": "문서에 없는 서양 기술 주장",
        "evidence_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
    }
    base.update(overrides)
    return base


def _create_body(*errors: dict[str, Any]) -> dict[str, Any]:
    return {
        "assignment_id": 42,
        "title": "Stage 2",
        "question": "질문",
        "flawed_ai_response": FLAWED,
        "expected_error_count": len(errors),
        "generated_errors": list(errors),
    }


def test_validate_create_response_accepts_valid_body() -> None:
    second_sentence = (
        "장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요."
    )
    second_start = FLAWED.find(second_sentence)
    validate_stage2_create_response(
        _create_body(
            _error_item(),
            _error_item(
                answer_id=2,
                error_sentence=second_sentence,
                error_type="PERSONA_BIAS",
                start_index=second_start,
                end_index=second_start + len(second_sentence),
                correct_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
                hallucination_reason="페르소나 편향",
                evidence_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
            ),
        ),
        expected_error_count=2,
        allowed_types=ALLOWED_TYPES,
        document_text=DOCUMENT_TEXT,
    )


def test_validate_create_response_rejects_count_mismatch() -> None:
    with pytest.raises(Stage2E2EValidationError, match="count mismatch"):
        validate_stage2_create_response(
            _create_body(_error_item()),
            expected_error_count=2,
            allowed_types=ALLOWED_TYPES,
        )


def test_validate_generated_error_rejects_bad_index_span() -> None:
    with pytest.raises(Stage2E2EValidationError, match="index span"):
        validate_generated_error_item(
            _error_item(start_index=0, end_index=5),
            flawed_ai_response=FLAWED,
            allowed_types=ALLOWED_TYPES,
        )


def test_validate_generated_error_rejects_missing_evidence_in_document() -> None:
    with pytest.raises(Stage2E2EValidationError, match="evidence_sentence"):
        validate_generated_error_item(
            _error_item(evidence_sentence="문서에 없는 근거"),
            flawed_ai_response=FLAWED,
            allowed_types=ALLOWED_TYPES,
            document_text=DOCUMENT_TEXT,
        )


def test_baseline_fixture_fails_e2e_validation(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    result = stage2_langflow_baseline_fixture["langflow_result"]
    inp = stage2_langflow_baseline_fixture["input"]
    body = {
        "assignment_id": 1,
        "title": "baseline",
        "question": inp["question"],
        "flawed_ai_response": result["flawed_ai_response"],
        "expected_error_count": inp["expected_error_count"],
        "generated_errors": [
            {
                "answer_id": index + 1,
                **error,
            }
            for index, error in enumerate(result["generated_errors"])
        ],
    }

    with pytest.raises(Stage2E2EValidationError):
        validate_stage2_create_response(
            body,
            expected_error_count=2,
            allowed_types=set(inp["hallucination_types"]),
            document_text=inp["document_text"],
        )
