"""Tests for Stage 2 generation orchestrator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import Stage2LangflowServiceUnavailableError
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
)
from app.services.stage2_generation_orchestrator import (
    Stage2GenerationOrchestrator,
    build_stage2_validation_feedback,
)
from app.services.stage2_generation_validator import Stage2GenerationValidationCode
from app.services.stage2_index_calculator import Stage2IndexCalculationCode

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


def _valid_pair() -> tuple[Stage2GeneratedErrorDraft, Stage2GeneratedErrorDraft]:
    return (
        _error(),
        _error(
            error_sentence="장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요.",
            error_type="PERSONA_BIAS",
            correct_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
            hallucination_reason="페르소나 편향",
            evidence_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
            retrieved_context=None,
        ),
    )


def _langflow_result(*errors: Stage2GeneratedErrorDraft) -> Stage2LangflowGenerationResult:
    return Stage2LangflowGenerationResult(
        flawed_ai_response=FLAWED_RESPONSE,
        generated_errors=list(errors),
    )


def test_build_validation_feedback_merges_validator_and_index_codes() -> None:
    feedback = build_stage2_validation_feedback(
        validation_codes=(Stage2GenerationValidationCode.ERROR_COUNT_MISMATCH,),
        index_codes=(Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND,),
    )

    assert "ERROR_COUNT_MISMATCH" in feedback
    assert "ERROR_SENTENCE_NOT_FOUND" in feedback
    assert "planned_errors 개수" in feedback


@pytest.mark.asyncio
async def test_orchestrator_success_applies_indices_and_validates() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_langflow_result(*_valid_pair())
    )

    orchestrator = Stage2GenerationOrchestrator(langflow_client=langflow_client)
    pipeline = await orchestrator.generate(
        document_text=DOCUMENT_TEXT,
        question="장영실의 발명품에 대해 설명해줘.",
        persona="장영실이 연을 만들었다고 믿는 선생님",
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )

    assert pipeline.validation.is_valid is True
    assert pipeline.index_application.applied is True
    assert pipeline.is_ready_for_save is True
    assert pipeline.generation_attempts == 1
    assert pipeline.retrieval_input.strategy == "SAME_DOCUMENT_THEN_SYNTHETIC"
    assert pipeline.candidate_chunk_ids

    first_error = pipeline.result.generated_errors[0]
    assert first_error.start_index is not None
    assert first_error.end_index is not None
    assert (
        FLAWED_RESPONSE[first_error.start_index : first_error.end_index]
        == first_error.error_sentence
    )

    call_kwargs = langflow_client.run_stage2_hallucination.await_args.kwargs
    assert isinstance(call_kwargs["retrieval_input"], Stage2RetrievalInput)
    assert call_kwargs["validation_feedback"] == ""
    assert langflow_client.run_stage2_hallucination.await_count == 1


@pytest.mark.asyncio
async def test_orchestrator_retries_once_and_succeeds_on_second_attempt() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        side_effect=[
            _langflow_result(_error()),
            _langflow_result(*_valid_pair()),
        ]
    )

    orchestrator = Stage2GenerationOrchestrator(langflow_client=langflow_client)
    pipeline = await orchestrator.generate(
        document_text=DOCUMENT_TEXT,
        question="질문",
        persona="페르소나",
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )

    assert pipeline.is_ready_for_save is True
    assert pipeline.generation_attempts == 2
    assert langflow_client.run_stage2_hallucination.await_count == 2

    second_call_kwargs = langflow_client.run_stage2_hallucination.await_args_list[1].kwargs
    assert "ERROR_COUNT_MISMATCH" in second_call_kwargs["validation_feedback"]


@pytest.mark.asyncio
async def test_orchestrator_raises_after_retry_exhausted() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_langflow_result(_error())
    )

    orchestrator = Stage2GenerationOrchestrator(langflow_client=langflow_client)

    with pytest.raises(Stage2LangflowServiceUnavailableError):
        await orchestrator.generate(
            document_text=DOCUMENT_TEXT,
            question="질문",
            persona="페르소나",
            hallucination_types=HALLUCINATION_TYPES,
            expected_error_count=2,
        )

    assert langflow_client.run_stage2_hallucination.await_count == 2


@pytest.mark.asyncio
async def test_orchestrator_does_not_retry_langflow_transport_failure() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        side_effect=Stage2LangflowServiceUnavailableError()
    )

    orchestrator = Stage2GenerationOrchestrator(langflow_client=langflow_client)

    with pytest.raises(Stage2LangflowServiceUnavailableError):
        await orchestrator.generate(
            document_text=DOCUMENT_TEXT,
            question="질문",
            persona="페르소나",
            hallucination_types=HALLUCINATION_TYPES,
            expected_error_count=2,
        )

    assert langflow_client.run_stage2_hallucination.await_count == 1


@pytest.mark.asyncio
async def test_orchestrator_reuses_retrieval_input_on_retry() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        side_effect=[
            _langflow_result(_error()),
            _langflow_result(*_valid_pair()),
        ]
    )

    orchestrator = Stage2GenerationOrchestrator(langflow_client=langflow_client)
    await orchestrator.generate(
        document_text=DOCUMENT_TEXT,
        question="질문",
        persona="페르소나",
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )

    first_retrieval = langflow_client.run_stage2_hallucination.await_args_list[0].kwargs[
        "retrieval_input"
    ]
    second_retrieval = langflow_client.run_stage2_hallucination.await_args_list[1].kwargs[
        "retrieval_input"
    ]
    assert first_retrieval is second_retrieval


@pytest.mark.asyncio
async def test_orchestrator_marks_index_failure_when_sentence_missing() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_langflow_result(
            _error(error_sentence="본문에 없는 문장입니다."),
            _valid_pair()[1],
        )
    )

    orchestrator = Stage2GenerationOrchestrator(langflow_client=langflow_client)

    with pytest.raises(Stage2LangflowServiceUnavailableError):
        await orchestrator.generate(
            document_text=DOCUMENT_TEXT,
            question="질문",
            persona="페르소나",
            hallucination_types=HALLUCINATION_TYPES,
            expected_error_count=2,
        )

    second_call_kwargs = langflow_client.run_stage2_hallucination.await_args_list[1].kwargs
    assert "ERROR_SENTENCE_NOT_FOUND" in second_call_kwargs["validation_feedback"]
