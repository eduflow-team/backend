"""Tests for Stage2 set create API (POST /teacher/assignments/step2/set)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import Stage2LangflowServiceUnavailableError
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.enums import AssignmentPublishStatus
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.user import User
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
)
from app.services.stage2_generation_orchestrator import Stage2GenerationPipelineResult
from app.services.stage2_generation_validator import Stage2GenerationValidationResult
from app.services.stage2_index_calculator import Stage2IndexApplicationResult
from app.services.stage2_service import Stage2Service

DOCUMENT_TEXT = "장영실은 자격루와 측우기를 발명했습니다."
HALLUCINATION_TYPES_RAW = '["PERSONA_BIAS", "INFORMATION_FABRICATION"]'
FUTURE_DUE_AT = datetime.now(UTC) + timedelta(days=7)


def _ready_pipeline() -> Stage2GenerationPipelineResult:
    flawed = "장영실은 하늘을 나는 연을 발명했습니다."
    error = Stage2GeneratedErrorDraft.model_validate(
        {
            "error_sentence": "하늘을 나는 연을 발명했습니다.",
            "error_type": "PERSONA_BIAS",
            "start_index": 4,
            "end_index": 22,
            "correct_sentence": "자격루와 측우기를 발명했습니다.",
            "hallucination_reason": "페르소나 편향",
            "evidence_sentence": "장영실은 자격루와 측우기를 발명했습니다.",
        }
    )
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=flawed,
        generated_errors=[error],
    )
    return Stage2GenerationPipelineResult(
        result=result,
        retrieval_input=Stage2RetrievalInput(candidate_chunks=[]),
        validation=Stage2GenerationValidationResult(is_valid=True, codes=()),
        index_application=Stage2IndexApplicationResult(
            result=result,
            codes=(),
            applied=True,
        ),
        generation_attempts=1,
    )


def _build_service() -> Stage2Service:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return Stage2Service(session)


def _teacher() -> User:
    return User(user_id=1, role="TEACHER", class_id=10)


def _upload_file() -> AsyncMock:
    upload = AsyncMock()
    upload.filename = "lesson.txt"
    upload.read = AsyncMock(return_value=DOCUMENT_TEXT.encode("utf-8"))
    return upload


def _with_id(entity, entity_id: int):
    if isinstance(entity, Assignment):
        entity.assignment_id = entity_id
    elif isinstance(entity, Document):
        entity.document_id = entity_id
    elif isinstance(entity, Stage2AssignmentDetail):
        entity.detail_id = entity_id
    elif isinstance(entity, Stage2ErrorAnswer):
        entity.answer_id = entity_id
    return entity


@pytest.mark.asyncio
async def test_create_set_returns_cards_with_shared_set_id(tmp_path: Path) -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())

    assignment_ids = iter([101, 102])
    created_assignments: list[Assignment] = []

    async def _create_assignment(entity: Assignment) -> Assignment:
        entity.assignment_id = next(assignment_ids)
        created_assignments.append(entity)
        return entity

    service.assignment_repository.create = AsyncMock(side_effect=_create_assignment)
    service.assignment_repository.update = AsyncMock(side_effect=lambda entity: entity)
    service.document_repository.create = AsyncMock(
        side_effect=lambda doc: _with_id(doc, 500)
    )
    service.stage2_detail_repository.create = AsyncMock(
        side_effect=lambda detail: _with_id(detail, 600)
    )
    service.stage2_detail_repository.set_generation_metadata = AsyncMock()
    service.stage2_error_answer_repository.create = AsyncMock(
        side_effect=lambda row: _with_id(row, 700)
    )
    service.generation_orchestrator.generate = AsyncMock(return_value=_ready_pipeline())

    with (
        patch(
            "app.services.stage2_service.extract_text_from_upload",
            return_value=DOCUMENT_TEXT,
        ),
        patch("app.services.stage2_service._UPLOAD_DIR", tmp_path / "uploads"),
    ):
        response = await service.create_step2_set(
            1,
            title="세트 과제",
            subject="과학",
            question="장영실의 업적은?",
            persona="페르소나",
            due_at=FUTURE_DUE_AT,
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            card_count=2,
            file=_upload_file(),
        )

    assert response.set_id == 101
    assert response.card_count == 2
    assert len(response.cards) == 2
    assert response.cards[0].assignment_id == 101
    assert response.cards[1].assignment_id == 102
    assert all(
        card.publish_status == AssignmentPublishStatus.DRAFT.value
        for card in response.cards
    )
    assert created_assignments[0].set_id == 101
    assert created_assignments[1].set_id == 101
    assert service.generation_orchestrator.generate.await_count == 2


@pytest.mark.asyncio
async def test_create_set_raises_when_all_cards_fail() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.generation_orchestrator.generate = AsyncMock(
        return_value=Stage2GenerationPipelineResult(
            result=Stage2LangflowGenerationResult(
                flawed_ai_response="x",
                generated_errors=[],
            ),
            retrieval_input=Stage2RetrievalInput(candidate_chunks=[]),
            validation=Stage2GenerationValidationResult(
                is_valid=False,
                codes=("ERROR_COUNT_MISMATCH",),
            ),
            index_application=Stage2IndexApplicationResult(
                result=Stage2LangflowGenerationResult(
                    flawed_ai_response="x",
                    generated_errors=[],
                ),
                codes=(),
                applied=False,
            ),
            generation_attempts=2,
        )
    )

    with patch(
        "app.services.stage2_service.extract_text_from_upload",
        return_value=DOCUMENT_TEXT,
    ):
        with pytest.raises(Stage2LangflowServiceUnavailableError):
            await service.create_step2_set(
                1,
                title="세트 과제",
                subject="과학",
                question="질문",
                persona="페르소나",
                due_at=FUTURE_DUE_AT,
                hallucination_types_raw=HALLUCINATION_TYPES_RAW,
                card_count=2,
                file=_upload_file(),
            )
