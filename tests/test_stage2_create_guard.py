"""Tests for Stage 2 create save guard (step 11)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import Stage2LangflowServiceUnavailableError
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.user import User
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
)
from app.services.stage2_generation_orchestrator import Stage2GenerationPipelineResult
from app.services.stage2_generation_validator import (
    Stage2GenerationValidationCode,
    Stage2GenerationValidationResult,
)
from app.services.stage2_index_calculator import Stage2IndexApplicationResult
from app.services.stage2_service import Stage2Service

DOCUMENT_TEXT = "장영실은 자격루와 측우기를 발명했습니다."
HALLUCINATION_TYPES_RAW = '["PERSONA_BIAS"]'


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


def _invalid_pipeline() -> Stage2GenerationPipelineResult:
    flawed = "장영실은 하늘을 나는 연을 발명했습니다."
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=flawed,
        generated_errors=[],
    )
    return Stage2GenerationPipelineResult(
        result=result,
        retrieval_input=Stage2RetrievalInput(candidate_chunks=[]),
        validation=Stage2GenerationValidationResult(
            is_valid=False,
            codes=(Stage2GenerationValidationCode.ERROR_COUNT_MISMATCH,),
        ),
        index_application=Stage2IndexApplicationResult(
            result=result,
            codes=(),
            applied=False,
        ),
        generation_attempts=2,
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


@pytest.mark.asyncio
async def test_create_raises_when_generation_fails_before_save() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.generation_orchestrator.generate = AsyncMock(
        side_effect=Stage2LangflowServiceUnavailableError()
    )
    service.assignment_repository.create = AsyncMock()

    with pytest.raises(Stage2LangflowServiceUnavailableError):
        await service.create_step2_assignment(
            1,
            title="Stage 2",
            subject="과학",
            question="장영실의 업적은?",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=1,
            file=_upload_file(),
        )

    service.assignment_repository.create.assert_not_called()
    service.session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_raises_when_pipeline_not_ready_for_save() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.generation_orchestrator.generate = AsyncMock(return_value=_invalid_pipeline())
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
            question="장영실의 업적은?",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=1,
            file=_upload_file(),
        )

    service.assignment_repository.create.assert_not_called()
    service.session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_rolls_back_and_removes_upload_on_commit_failure(
    tmp_path: Path,
) -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.generation_orchestrator.generate = AsyncMock(return_value=_ready_pipeline())

    assignment = Assignment(assignment_id=99)
    document = Document(document_id=501)
    detail = Stage2AssignmentDetail(detail_id=701)
    error_row = Stage2ErrorAnswer(answer_id=801)

    service.assignment_repository.create = AsyncMock(return_value=assignment)
    service.document_repository.create = AsyncMock(return_value=document)
    service.stage2_detail_repository.create = AsyncMock(return_value=detail)
    service.stage2_error_answer_repository.create = AsyncMock(return_value=error_row)
    service.session.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

    upload_dir = tmp_path / "uploads" / "stage2"
    with (
        patch(
            "app.services.stage2_service.extract_text_from_upload",
            return_value=DOCUMENT_TEXT,
        ),
        patch("app.services.stage2_service._UPLOAD_DIR", upload_dir),
        pytest.raises(RuntimeError, match="commit failed"),
    ):
        await service.create_step2_assignment(
            1,
            title="Stage 2",
            subject="과학",
            question="장영실의 업적은?",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=1,
            file=_upload_file(),
        )

    service.session.rollback.assert_awaited_once()
    saved_file = upload_dir / "99" / "lesson.txt"
    assert not saved_file.exists()
    assert not (upload_dir / "99").exists()


@pytest.mark.asyncio
async def test_create_persists_when_pipeline_ready_for_save(tmp_path: Path) -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_teacher())
    service.generation_orchestrator.generate = AsyncMock(return_value=_ready_pipeline())

    assignment = Assignment(assignment_id=42)
    document = Document(document_id=502)
    detail = Stage2AssignmentDetail(detail_id=702)
    error_row = Stage2ErrorAnswer(answer_id=802)

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
            question="장영실의 업적은?",
            persona="페르소나",
            hallucination_types_raw=HALLUCINATION_TYPES_RAW,
            expected_error_count=1,
            file=_upload_file(),
        )

    assert response.assignment_id == 42
    assert len(response.generated_errors) == 1
    service.stage2_detail_repository.set_generation_metadata.assert_awaited_once()
    metadata_arg = (
        service.stage2_detail_repository.set_generation_metadata.await_args.args[1]
    )
    assert metadata_arg.flow_version == "stage2-v2"
    assert metadata_arg.generation_attempts == 1
    assert metadata_arg.validation_codes == []
    service.session.commit.assert_awaited_once()
    service.session.rollback.assert_not_called()
    assert (upload_dir / "42" / "lesson.txt").exists()
