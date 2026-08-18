"""Tests for Stage2 set create response validation helpers."""

from __future__ import annotations

import pytest

from app.services.stage2_response_validation import (
    Stage2E2EValidationError,
    validate_stage2_set_create_response,
)


def _card_body() -> dict:
    return {
        "assignment_id": 101,
        "card_index": 0,
        "title": "세트 · 카드 1",
        "flawed_ai_response": "장영실은 하늘을 나는 연을 발명했습니다.",
        "expected_error_count": 1,
        "generation_error_type": "PERSONA_BIAS",
        "generated_errors": [
            {
                "answer_id": 1,
                "error_sentence": "하늘을 나는 연을 발명했습니다.",
                "error_type": "PERSONA_BIAS",
                "start_index": 4,
                "end_index": 22,
                "correct_sentence": "자격루와 측우기를 발명했습니다.",
                "hallucination_reason": "페르소나 편향",
                "evidence_sentence": "장영실은 자격루와 측우기를 발명했습니다.",
            }
        ],
        "publish_status": "DRAFT",
        "generation_succeeded": True,
        "failure_codes": [],
    }


def test_validate_stage2_set_create_response_accepts_valid_body() -> None:
    validate_stage2_set_create_response(
        {
            "set_id": 101,
            "title": "세트",
            "question": "질문",
            "card_count": 1,
            "cards": [_card_body()],
            "failed_cards": [],
        },
        card_count=1,
        allowed_types={"PERSONA_BIAS"},
        document_text="장영실은 자격루와 측우기를 발명했습니다.",
    )


def test_validate_stage2_set_create_response_rejects_wrong_error_count() -> None:
    card = _card_body()
    card["expected_error_count"] = 2
    with pytest.raises(Stage2E2EValidationError):
        validate_stage2_set_create_response(
            {
                "set_id": 101,
                "title": "세트",
                "question": "질문",
                "card_count": 1,
                "cards": [card],
                "failed_cards": [],
            },
            card_count=1,
            allowed_types={"PERSONA_BIAS"},
        )
