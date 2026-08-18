"""Tests for Stage2 student publish guard and hint validation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import AssignmentNotFoundError, InvalidStage2HighlightError
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.enums import AssignmentPublishStatus, ProgressStatus
from app.models.stage import Stage2AssignmentDetail
from app.models.student_status import StudentAssignmentStatus
from app.models.user import User
from app.schemas.stage2 import Step2HighlightRequest, Step2HighlightSubmissionItem
from app.services.stage2_service import Stage2Service


def _build_service() -> Stage2Service:
    session = AsyncMock()
    session.commit = AsyncMock()
    return Stage2Service(session)


def _student() -> User:
    return User(user_id=10, role="STUDENT", class_id=1)


def _draft_assignment() -> Assignment:
    return Assignment(
        assignment_id=42,
        teacher_id=1,
        class_id=1,
        title="Draft",
        stage=2,
        publish_status=AssignmentPublishStatus.DRAFT.value,
    )


@pytest.mark.asyncio
async def test_student_get_step2_rejects_draft_assignment() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_student())
    service.assignment_repository.get_by_id = AsyncMock(return_value=_draft_assignment())

    with pytest.raises(AssignmentNotFoundError):
        await service.get_step2_assignment(10, 42)


@pytest.mark.asyncio
async def test_submit_highlight_rejects_error_type_outside_hints() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_student())
    service.assignment_repository.get_by_id = AsyncMock(
        return_value=Assignment(
            assignment_id=42,
            teacher_id=1,
            class_id=1,
            title="Published",
            stage=2,
            max_attempts=5,
            publish_status=AssignmentPublishStatus.PUBLISHED.value,
        )
    )
    service.stage2_detail_repository.get_by_assignment_id = AsyncMock(
        return_value=Stage2AssignmentDetail(
            detail_id=1,
            assignment_id=42,
            document_id=1,
            question="질문",
            persona="페르소나",
            hallucinated_ai_answer="답변",
            hallucination_types=["PERSONA_BIAS"],
            expected_error_count=1,
        )
    )
    service.status_repository.get_or_create = AsyncMock(
        return_value=StudentAssignmentStatus(
            user_id=10,
            assignment_id=42,
            progress_status=ProgressStatus.IN_PROGRESS.value,
            remaining_attempts=4,
        )
    )
    service.highlight_repository.list_by_user_and_assignment = AsyncMock(return_value=[])

    payload = Step2HighlightRequest(
        submissions=[
            Step2HighlightSubmissionItem(
                highlighted_text="오류 문장",
                student_error_type="RETRIEVAL_ERROR",
                student_reason="이유",
            )
        ]
    )

    with pytest.raises(InvalidStage2HighlightError):
        await service.submit_highlight(10, 42, payload)
