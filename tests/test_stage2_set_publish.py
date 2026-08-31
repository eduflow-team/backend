"""Tests for Stage2 set get/publish APIs."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import InvalidStage2SetError, Stage2SetNotFoundError
from app.models.assignment import Assignment
from app.models.enums import AssignmentPublishStatus
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.user import User
from app.schemas.stage2 import Stage2SetPublishRequest
from app.services.stage2_service import Stage2Service


def _build_service() -> Stage2Service:
    session = AsyncMock()
    session.commit = AsyncMock()
    return Stage2Service(session)


def _teacher() -> User:
    return User(user_id=1, role="TEACHER", class_id=10)


@pytest.mark.asyncio
async def test_get_step2_set_returns_preview_cards() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    assignments = [
        Assignment(
            assignment_id=101,
            teacher_id=1,
            class_id=10,
            title="세트 · 카드 1",
            stage=2,
            set_id=101,
            publish_status=AssignmentPublishStatus.DRAFT.value,
        ),
        Assignment(
            assignment_id=102,
            teacher_id=1,
            class_id=10,
            title="세트 · 카드 2",
            stage=2,
            set_id=101,
            publish_status=AssignmentPublishStatus.DRAFT.value,
        ),
    ]
    service.assignment_repository.list_by_set_id = AsyncMock(return_value=assignments)
    service.stage2_detail_repository.get_by_assignment_id = AsyncMock(
        side_effect=[
            Stage2AssignmentDetail(
                detail_id=1,
                assignment_id=101,
                document_id=1,
                question="질문",
                persona="페르소나",
                hallucinated_ai_answer="답변1",
                hallucination_types=["PERSONA_BIAS"],
                expected_error_count=1,
            ),
            Stage2AssignmentDetail(
                detail_id=2,
                assignment_id=102,
                document_id=2,
                question="질문",
                persona="페르소나",
                hallucinated_ai_answer="답변2",
                hallucination_types=["PERSONA_BIAS"],
                expected_error_count=1,
            ),
        ]
    )
    service.stage2_error_answer_repository.list_by_assignment_id = AsyncMock(
        return_value=[
            Stage2ErrorAnswer(
                answer_id=1,
                assignment_id=101,
                detail_id=1,
                error_sentence="오류",
                error_type="PERSONA_BIAS",
            )
        ]
    )

    response = await service.get_step2_set(1, 101)

    assert response.set_id == 101
    assert response.title == "세트"
    assert len(response.cards) == 2
    assert response.hallucination_type_hints == ["PERSONA_BIAS"]


@pytest.mark.asyncio
async def test_publish_step2_set_updates_selected_cards() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    assignments = [
        Assignment(
            assignment_id=101,
            teacher_id=1,
            class_id=10,
            title="세트 · 카드 1",
            stage=2,
            set_id=101,
            publish_status=AssignmentPublishStatus.DRAFT.value,
        ),
        Assignment(
            assignment_id=102,
            teacher_id=1,
            class_id=10,
            title="세트 · 카드 2",
            stage=2,
            set_id=101,
            publish_status=AssignmentPublishStatus.DRAFT.value,
        ),
    ]
    service.assignment_repository.list_by_set_id = AsyncMock(return_value=assignments)
    service.assignment_repository.update = AsyncMock(side_effect=lambda entity: entity)

    response = await service.publish_step2_set(
        1,
        101,
        Stage2SetPublishRequest(assignment_ids=[101]),
    )

    assert response.set_id == 101
    assert response.published_assignment_ids == [101]
    assert assignments[0].publish_status == AssignmentPublishStatus.PUBLISHED.value
    assert assignments[1].publish_status == AssignmentPublishStatus.DRAFT.value
    service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_step2_set_rejects_unknown_assignment_id() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.assignment_repository.list_by_set_id = AsyncMock(
        return_value=[
            Assignment(
                assignment_id=101,
                teacher_id=1,
                class_id=10,
                title="세트",
                stage=2,
                set_id=101,
                publish_status=AssignmentPublishStatus.DRAFT.value,
            )
        ]
    )

    with pytest.raises(InvalidStage2SetError):
        await service.publish_step2_set(
            1,
            101,
            Stage2SetPublishRequest(assignment_ids=[999]),
        )


@pytest.mark.asyncio
async def test_get_step2_set_not_found_for_other_teacher() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.assignment_repository.list_by_set_id = AsyncMock(
        return_value=[
            Assignment(
                assignment_id=101,
                teacher_id=99,
                class_id=10,
                title="세트",
                stage=2,
                set_id=101,
                publish_status=AssignmentPublishStatus.DRAFT.value,
            )
        ]
    )

    with pytest.raises(Stage2SetNotFoundError):
        await service.get_step2_set(1, 101)
