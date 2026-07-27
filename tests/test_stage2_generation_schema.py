"""Tests for Stage 2 Langflow internal generation schemas."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    parse_stage2_generated_errors,
    parse_stage2_langflow_generation_result,
)


def _valid_error(**overrides: Any) -> dict[str, Any]:
    base = {
        "error_sentence": "특히 자격루는 서양에서 온 기계라고 알려져 있어요.",
        "error_type": "RETRIEVAL_ERROR",
        "correct_sentence": "자격루는 물의 흐름을 이용한 자동 물시계입니다.",
        "hallucination_reason": "문서에 없는 서양 기술 주장",
        "evidence_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
    }
    base.update(overrides)
    return base


def test_parse_valid_error_draft() -> None:
    draft = Stage2GeneratedErrorDraft.model_validate(_valid_error())
    assert draft.error_type == "RETRIEVAL_ERROR"
    assert draft.retrieval_source is None


def test_parse_error_draft_with_retrieval_metadata() -> None:
    draft = Stage2GeneratedErrorDraft.model_validate(
        _valid_error(
            retrieval_source="same_document",
            retrieved_context="  관련 없는 청크 텍스트  ",
        )
    )
    assert draft.retrieval_source == "SAME_DOCUMENT"
    assert draft.retrieved_context == "관련 없는 청크 텍스트"


def test_parse_baseline_fixture_errors(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    raw_errors = stage2_langflow_baseline_fixture["langflow_result"]["generated_errors"]
    drafts = parse_stage2_generated_errors(raw_errors)
    assert len(drafts) == 2
    assert drafts[0].error_type == "RETRIEVAL_ERROR"
    assert drafts[1].error_type == "PERSONA_BIAS"


def test_parse_langflow_generation_result(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    langflow_result = stage2_langflow_baseline_fixture["langflow_result"]
    parsed = parse_stage2_langflow_generation_result(
        flawed_ai_response=langflow_result["flawed_ai_response"],
        raw_errors=langflow_result["generated_errors"],
    )
    assert isinstance(parsed, Stage2LangflowGenerationResult)
    assert len(parsed.generated_errors) == 2


@pytest.mark.parametrize(
    "missing_field",
    [
        "error_sentence",
        "error_type",
        "correct_sentence",
        "hallucination_reason",
        "evidence_sentence",
    ],
)
def test_rejects_missing_required_field(missing_field: str) -> None:
    payload = _valid_error()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        Stage2GeneratedErrorDraft.model_validate(payload)


def test_rejects_empty_required_string() -> None:
    with pytest.raises(ValidationError):
        Stage2GeneratedErrorDraft.model_validate(_valid_error(error_sentence="   "))


def test_rejects_invalid_error_type() -> None:
    with pytest.raises(ValidationError):
        Stage2GeneratedErrorDraft.model_validate(_valid_error(error_type="UNKNOWN_TYPE"))


def test_rejects_invalid_retrieval_source() -> None:
    with pytest.raises(ValidationError):
        Stage2GeneratedErrorDraft.model_validate(
            _valid_error(retrieval_source="WRONG_SOURCE")
        )


def test_ignores_unknown_extra_fields() -> None:
    draft = Stage2GeneratedErrorDraft.model_validate(
        _valid_error(unexpected_field="ignored")
    )
    assert draft.error_type == "RETRIEVAL_ERROR"
