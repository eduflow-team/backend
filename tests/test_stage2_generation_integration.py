"""Integration tests for Stage 2 generation pipeline (mock Langflow)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import Stage2LangflowServiceUnavailableError
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.user import User
from app.schemas.stage2 import Stage2CreateResponse
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)
from app.services.stage2_generation_metadata import build_stage2_generation_metadata
from app.services.stage2_generation_orchestrator import Stage2GenerationOrchestrator
from app.services.stage2_service import Stage2Service

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
HALLUCINATION_TYPES_RAW = '["RETRIEVAL_ERROR", "PERSONA_BIAS"]'


def _error(**overrides: Any) -> Stage2GeneratedErrorDraft:
    base = {
        "error_sentence": "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요.",
        "error_type": "RETRIEVAL_ERROR",
        "correct_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
        "hallucination_reason": "문서에 없는 서양 기술 주장",
        "evidence_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
        "retrieved_context": "동일 PDF distractor 청크",
        "retrieval_source": "SAME_DOCUMENT",
    }
    base.update(overrides)
    return Stage2GeneratedErrorDraft.model_validate(base)


def _valid_langflow_result(**retrieval_overrides: Any) -> Stage2LangflowGenerationResult:
    return Stage2LangflowGenerationResult(
        flawed_ai_response=FLAWED_RESPONSE,
        generated_errors=[
            _error(**retrieval_overrides),
            _error(
                error_sentence="장영실은 자격루뿐만 아니라, 하늘을 나는 연을 만들어 실험했다는 이야기도 있어요.",
                error_type="PERSONA_BIAS",
                correct_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
                hallucination_reason="페르소나 편향",
                evidence_sentence="장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.",
                retrieved_context=None,
                retrieval_source=None,
            ),
        ],
    )


def _orchestrator_with_client(langflow_client: AsyncMock) -> Stage2GenerationOrchestrator:
    return Stage2GenerationOrchestrator(langflow_client=langflow_client)


def _build_service_with_orchestrator(
    langflow_client: AsyncMock,
) -> Stage2Service:
    service = Stage2Service(AsyncMock())
    service.session.commit = AsyncMock()
    service.session.rollback = AsyncMock()
    service.generation_orchestrator = _orchestrator_with_client(langflow_client)
    return service


def _teacher() -> User:
    return User(user_id=1, role="TEACHER", class_id=10)


def _upload_file() -> AsyncMock:
    upload = AsyncMock()
    upload.filename = "lesson.txt"
    upload.read = AsyncMock(return_value=DOCUMENT_TEXT.encode("utf-8"))
    return upload


@pytest.mark.asyncio
async def test_integration_first_attempt_success() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_valid_langflow_result()
    )
    orchestrator = _orchestrator_with_client(langflow_client)

    pipeline = await orchestrator.generate(
        document_text=DOCUMENT_TEXT,
        question="장영실의 발명품에 대해 설명해줘.",
        persona="장영실이 연을 만들었다고 믿는 선생님",
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )

    assert pipeline.is_ready_for_save is True
    assert pipeline.generation_attempts == 1
    assert langflow_client.run_stage2_hallucination.await_count == 1
    assert pipeline.result.generated_errors[0].start_index is not None


@pytest.mark.asyncio
async def test_integration_retry_then_success() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        side_effect=[
            Stage2LangflowGenerationResult(
                flawed_ai_response=FLAWED_RESPONSE,
                generated_errors=[_error()],
            ),
            _valid_langflow_result(),
        ]
    )
    orchestrator = _orchestrator_with_client(langflow_client)

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
    second_feedback = langflow_client.run_stage2_hallucination.await_args_list[1].kwargs[
        "validation_feedback"
    ]
    assert "ERROR_COUNT_MISMATCH" in second_feedback


@pytest.mark.asyncio
async def test_integration_all_attempts_fail() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=Stage2LangflowGenerationResult(
            flawed_ai_response=FLAWED_RESPONSE,
            generated_errors=[_error()],
        )
    )
    orchestrator = _orchestrator_with_client(langflow_client)

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
async def test_integration_create_does_not_persist_on_pipeline_failure() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=Stage2LangflowGenerationResult(
            flawed_ai_response=FLAWED_RESPONSE,
            generated_errors=[_error()],
        )
    )
    service = _build_service_with_orchestrator(langflow_client)
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.assignment_repository.create = AsyncMock()

    with (
        patch(
            "app.services.stage2_service.extract_text_from_upload",
            return_value=DOCUMENT_TEXT,
        ),
        pytest.raises(Stage2LangflowServiceUnavailableError),
    ):
        await service.create_step2_assignment(
            1,
            title="Stage 2",
            subject="과학",
            question="장영실의 발명품에 대해 설명해줘.",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=2,
            file=_upload_file(),
        )

    service.assignment_repository.create.assert_not_called()
    service.session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_integration_same_document_retrieval_metadata() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_valid_langflow_result(
            retrieval_source="SAME_DOCUMENT",
            retrieved_context="동일 PDF distractor 청크",
        )
    )
    orchestrator = _orchestrator_with_client(langflow_client)

    pipeline = await orchestrator.generate(
        document_text=DOCUMENT_TEXT,
        question="질문",
        persona="페르소나",
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )
    metadata = build_stage2_generation_metadata(pipeline)

    assert metadata.retrieval_source == "SAME_DOCUMENT"
    assert metadata.retrieved_context == "동일 PDF distractor 청크"
    assert metadata.candidate_chunk_ids


@pytest.mark.asyncio
async def test_integration_synthetic_retrieval_metadata() -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_valid_langflow_result(
            retrieval_source="SYNTHETIC",
            retrieved_context="합성 distractor 문장",
        )
    )
    orchestrator = _orchestrator_with_client(langflow_client)

    pipeline = await orchestrator.generate(
        document_text=DOCUMENT_TEXT,
        question="질문",
        persona="페르소나",
        hallucination_types=HALLUCINATION_TYPES,
        expected_error_count=2,
    )
    metadata = build_stage2_generation_metadata(pipeline)

    assert metadata.retrieval_source == "SYNTHETIC"
    assert metadata.retrieved_context == "합성 distractor 문장"


@pytest.mark.asyncio
async def test_integration_create_response_matches_external_contract(
    tmp_path: Path,
) -> None:
    langflow_client = AsyncMock()
    langflow_client.run_stage2_hallucination = AsyncMock(
        return_value=_valid_langflow_result()
    )
    service = _build_service_with_orchestrator(langflow_client)
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())

    assignment = Assignment(assignment_id=42)
    document = Document(document_id=502)
    detail = Stage2AssignmentDetail(detail_id=702)
    error_row = Stage2ErrorAnswer(
        answer_id=802,
        error_sentence="특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요.",
        error_type="RETRIEVAL_ERROR",
        start_index=10,
        end_index=20,
        correct_sentence="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
        hallucination_reason="문서에 없는 서양 기술 주장",
        evidence_sentence="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
    )

    service.assignment_repository.create = AsyncMock(return_value=assignment)
    service.document_repository.create = AsyncMock(return_value=document)
    service.stage2_detail_repository.create = AsyncMock(return_value=detail)
    service.stage2_detail_repository.set_generation_metadata = AsyncMock(
        return_value=detail
    )
    service.stage2_error_answer_repository.create = AsyncMock(return_value=error_row)

    upload_dir = tmp_path / "uploads" / "stage2"
    with (
        patch(
            "app.services.stage2_service.extract_text_from_upload",
            return_value=DOCUMENT_TEXT,
        ),
        patch("app.services.stage2_service._UPLOAD_DIR", upload_dir),
    ):
        response = await service.create_step2_assignment(
            1,
            title="Stage 2",
            subject="과학",
            question="장영실의 발명품에 대해 설명해줘.",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=2,
            file=_upload_file(),
        )

    parsed = Stage2CreateResponse.model_validate(response.model_dump())
    assert parsed.assignment_id == 42
    assert parsed.expected_error_count == 2
    assert len(parsed.generated_errors) == 2
    assert set(parsed.model_fields) == set(Stage2CreateResponse.model_fields)
    error_item = parsed.generated_errors[0]
    assert set(error_item.model_fields) == {
        "answer_id",
        "error_sentence",
        "error_type",
        "start_index",
        "end_index",
        "correct_sentence",
        "hallucination_reason",
        "evidence_sentence",
    }
