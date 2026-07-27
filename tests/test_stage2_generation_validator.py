"""Tests for Stage 2 generation quality validator."""

from __future__ import annotations

from typing import Any

import pytest

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)
from app.services.stage2_generation_validator import (
    Stage2GenerationValidationCode,
    validate_stage2_generation_result,
)

DOCUMENT_TEXT = (
    "장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.\n"
    "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다."
)
FLAWED_RESPONSE = (
    "장영실은 정말 뛰어난 발명가였어요. "
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요. "
    "장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요."
)
HALLUCINATION_TYPES = ["RETRIEVAL_ERROR", "PERSONA_BIAS"]


def _error(**overrides: Any) -> Stage2GeneratedErrorDraft:
    base = {
        "error_sentence": "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요.",
        "error_type": "RETRIEVAL_ERROR",
        "correct_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
        "hallucination_reason": "문서에 없는 서양 기술 주장",
        "evidence_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
        "retrieved_context": "서양에서 전래된 천문 기구에 대한 설명",
    }
    base.update(overrides)
    return Stage2GeneratedErrorDraft.model_validate(base)


def _result(*errors: Stage2GeneratedErrorDraft) -> Stage2LangflowGenerationResult:
    return Stage2LangflowGenerationResult(
        flawed_ai_response=FLAWED_RESPONSE,
        generated_errors=list(errors),
    )


def test_valid_generation_passes() -> None:
    validation = validate_stage2_generation_result(
        result=_result(
            _error(),
            _error(
                error_sentence="장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요.",
                error_type="PERSONA_BIAS",
                correct_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
                hallucination_reason="페르소나 편향",
                evidence_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
                retrieved_context=None,
            ),
        ),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )
    assert validation.is_valid is True
    assert validation.codes == ()


def test_baseline_fixture_fails_retrieval_context_only(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    langflow_result = stage2_langflow_baseline_fixture["langflow_result"]
    inp = stage2_langflow_baseline_fixture["input"]
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=langflow_result["flawed_ai_response"],
        generated_errors=[
            Stage2GeneratedErrorDraft.model_validate(item)
            for item in langflow_result["generated_errors"]
        ],
    )

    validation = validate_stage2_generation_result(
        result=result,
        document_text=inp["document_text"],
        hallucination_types=inp["hallucination_types"],
        expected_error_count=inp["expected_error_count"],
    )

    assert validation.is_valid is False
    assert validation.codes == (Stage2GenerationValidationCode.RETRIEVAL_CONTEXT_MISSING,)


def test_error_count_mismatch() -> None:
    validation = validate_stage2_generation_result(
        result=_result(_error()),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )
    assert Stage2GenerationValidationCode.ERROR_COUNT_MISMATCH in validation.codes


def test_error_sentence_not_found() -> None:
    validation = validate_stage2_generation_result(
        result=_result(_error(error_sentence="문서에 없는 완전히 다른 문장입니다.")),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=1,
    )
    assert Stage2GenerationValidationCode.ERROR_SENTENCE_NOT_FOUND in validation.codes


def test_evidence_not_found() -> None:
    validation = validate_stage2_generation_result(
        result=_result(_error(evidence_sentence="PDF에 없는 근거 문장입니다.")),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=1,
    )
    assert Stage2GenerationValidationCode.EVIDENCE_NOT_FOUND in validation.codes


def test_invalid_error_type_not_in_teacher_selection() -> None:
    validation = validate_stage2_generation_result(
        result=_result(
            _error(
                error_type="INFORMATION_FABRICATION",
                retrieved_context=None,
            )
        ),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=1,
    )
    assert Stage2GenerationValidationCode.INVALID_ERROR_TYPE in validation.codes


def test_duplicated_error_sentence() -> None:
    duplicated = _error()
    validation = validate_stage2_generation_result(
        result=_result(duplicated, duplicated),
        document_text=DOCUMENT_TEXT,
        hallucination_types=["RETRIEVAL_ERROR"],
        expected_error_count=2,
    )
    assert Stage2GenerationValidationCode.DUPLICATED_ERROR in validation.codes


def test_retrieval_error_requires_retrieved_context() -> None:
    validation = validate_stage2_generation_result(
        result=_result(_error(retrieved_context=None)),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=1,
    )
    assert Stage2GenerationValidationCode.RETRIEVAL_CONTEXT_MISSING in validation.codes


@pytest.mark.parametrize(
    ("evidence_sentence", "should_pass"),
    [
        (
            "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
            True,
        ),
        ("존재하지 않는 근거", False),
    ],
)
def test_evidence_match_against_document(evidence_sentence: str, should_pass: bool) -> None:
    validation = validate_stage2_generation_result(
        result=_result(_error(evidence_sentence=evidence_sentence)),
        document_text=DOCUMENT_TEXT,
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=1,
    )
    if should_pass:
        assert Stage2GenerationValidationCode.EVIDENCE_NOT_FOUND not in validation.codes
    else:
        assert Stage2GenerationValidationCode.EVIDENCE_NOT_FOUND in validation.codes
