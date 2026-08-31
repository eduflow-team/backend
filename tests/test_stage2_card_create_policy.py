"""Tests for Stage2 single-card create policy (expected_error_count=1)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import InvalidStage2CreateError
from app.services.stage2_service import Stage2Service

HALLUCINATION_TYPES_RAW = '["PERSONA_BIAS"]'


def _build_service() -> Stage2Service:
    session = AsyncMock()
    return Stage2Service(session)


def _teacher():
    from app.models.user import User

    return User(user_id=1, role="TEACHER", class_id=10)


def _upload_file() -> AsyncMock:
    upload = AsyncMock()
    upload.filename = "lesson.txt"
    upload.read = AsyncMock(return_value=b"sample text")
    return upload


@pytest.mark.asyncio
async def test_create_rejects_expected_error_count_other_than_one() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())

    with pytest.raises(InvalidStage2CreateError):
        await service.create_step2_assignment(
            1,
            title="Stage 2",
            subject="과학",
            question="질문",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=2,
            file=_upload_file(),
        )
