"""Stage 2 과제 도메인 비즈니스 로직.

Langflow HTTP 호출은 AI 총괄 연동 전까지 mock 응답을 반환한다.
학생 하이라이트·correction 채점은 백엔드에서 처리한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.langflow_client import LangflowClient
from app.core.config import settings
from app.core.exceptions import (
    AssignmentNotFoundError,
    InvalidStage2CreateError,
    InvalidTokenError,
    Stage2AccessForbiddenError,
    Stage2DocumentProcessingError,
    Stage2FileTooLargeError,
    UnsupportedStage2FileTypeError,
)
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.enums import ProgressStatus
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.submission import Stage2HighlightSubmission
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.document import DocumentRepository
from app.repositories.stage import (
    Stage2DetailRepository,
    Stage2ErrorAnswerRepository,
    Stage2HighlightRepository,
)
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.user import UserRepository
from app.schemas.stage2 import (
    ALLOWED_HALLUCINATION_TYPES,
    HALLUCINATION_TYPE_OPTIONS,
    HallucinationTypeOption,
    Stage2AssignmentDetailResponse,
    Stage2AttemptsDetail,
    Stage2CreateResponse,
    Stage2GeneratedErrorItem,
)
from app.services.embedding_service import extract_text_from_upload

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf"}
_UPLOAD_DIR = Path("uploads/stage2")


class Stage2Service:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.stage2_detail_repository = Stage2DetailRepository(session)
        self.stage2_error_answer_repository = Stage2ErrorAnswerRepository(session)
        self.document_repository = DocumentRepository(session)
        self.status_repository = StudentAssignmentStatusRepository(session)
        self.highlight_repository = Stage2HighlightRepository(session)
        self.langflow_client = LangflowClient()

    async def create_step2_assignment(
        self,
        user_id: int,
        *,
        title: str,
        subject: str,
        question: str,
        persona: str,
        hallucination_types_raw: str,
        expected_error_count: int,
        file: UploadFile,
    ) -> Stage2CreateResponse:
        teacher = await self._get_authorized_teacher(user_id)
        if teacher.class_id is None:
            raise Stage2AccessForbiddenError()

        title = (title or "").strip()
        subject = (subject or "").strip()
        question = (question or "").strip()
        persona = (persona or "").strip()
        filename = (file.filename or "").strip()
        if not title or not subject or not question or not persona or not filename:
            raise InvalidStage2CreateError()

        if len(persona) > 100:
            raise InvalidStage2CreateError()

        hallucination_types = self._parse_hallucination_types(hallucination_types_raw)
        if not (1 <= expected_error_count <= 5):
            raise InvalidStage2CreateError()

        suffix = Path(filename).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise UnsupportedStage2FileTypeError()

        content = await file.read()
        if not content:
            raise InvalidStage2CreateError()
        if len(content) > settings.STAGE2_MAX_UPLOAD_BYTES:
            raise Stage2FileTooLargeError()

        try:
            raw_text = extract_text_from_upload(filename, content)
            if not raw_text.strip():
                raise Stage2DocumentProcessingError()
        except UnsupportedStage2FileTypeError:
            raise
        except Stage2DocumentProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("stage2 document processing failed")
            raise Stage2DocumentProcessingError() from exc

        langflow_result = await self.langflow_client.run_stage2_hallucination(
            document_text=raw_text,
            question=question,
            persona=persona,
            hallucination_types=hallucination_types,
            expected_error_count=expected_error_count,
        )

        generated_errors = langflow_result.generated_errors
        if len(generated_errors) < expected_error_count:
            logger.warning(
                "stage2 langflow returned %s errors, expected %s",
                len(generated_errors),
                expected_error_count,
            )

        assignment = Assignment(
            teacher_id=teacher.user_id,
            class_id=teacher.class_id,
            title=title,
            stage=2,
            subject=subject,
            description=question,
            max_attempts=settings.STAGE2_MAX_ATTEMPTS,
        )
        assignment = await self.assignment_repository.create(assignment)

        saved_path = await self._save_upload_file(
            assignment.assignment_id, filename, content
        )
        document = Document(
            assignment_id=assignment.assignment_id,
            subject=subject,
            filename=filename,
            file_path=str(saved_path),
            file_type=suffix.lstrip("."),
            raw_text=raw_text,
        )
        document = await self.document_repository.create(document)

        detail = Stage2AssignmentDetail(
            assignment_id=assignment.assignment_id,
            document_id=document.document_id,
            question=question,
            persona=persona,
            hallucinated_ai_answer=langflow_result.flawed_ai_response,
            hallucination_types=hallucination_types,
            expected_error_count=expected_error_count,
        )
        detail = await self.stage2_detail_repository.create(detail)

        response_errors: list[Stage2GeneratedErrorItem] = []
        for error in generated_errors:
            row = Stage2ErrorAnswer(
                assignment_id=assignment.assignment_id,
                detail_id=detail.detail_id,
                error_sentence=error.get("error_sentence"),
                error_type=error.get("error_type"),
                start_index=error.get("start_index"),
                end_index=error.get("end_index"),
                correct_sentence=error.get("correct_sentence"),
                hallucination_reason=error.get("hallucination_reason"),
                evidence_sentence=error.get("evidence_sentence"),
            )
            row = await self.stage2_error_answer_repository.create(row)
            response_errors.append(
                Stage2GeneratedErrorItem(
                    answer_id=row.answer_id,
                    error_sentence=row.error_sentence or "",
                    error_type=row.error_type or "",
                    start_index=row.start_index or 0,
                    end_index=row.end_index or 0,
                    correct_sentence=row.correct_sentence or "",
                    hallucination_reason=row.hallucination_reason or "",
                    evidence_sentence=row.evidence_sentence or "",
                )
            )

        await self.session.commit()

        return Stage2CreateResponse(
            assignment_id=assignment.assignment_id,
            title=title,
            question=question,
            flawed_ai_response=langflow_result.flawed_ai_response,
            expected_error_count=expected_error_count,
            generated_errors=response_errors,
        )

    # ------------------------------------------------------------------
    # Student: detail
    # ------------------------------------------------------------------

    async def get_step2_assignment(
        self, user_id: int, assignment_id: int
    ) -> Stage2AssignmentDetailResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage2_assignment_for_student(
            student, assignment_id
        )

        document = await self.document_repository.get_by_id(detail.document_id)
        reference_text = document.raw_text if document and document.raw_text else ""

        max_attempts = assignment.max_attempts or settings.STAGE2_MAX_ATTEMPTS
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )
        await self.session.commit()

        highlights = await self.highlight_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        used_attempts = len(highlights)
        remaining = (
            status.remaining_attempts
            if status.remaining_attempts is not None
            else max(0, max_attempts - used_attempts)
        )

        cleared_highlights = self._collect_cleared_highlights(highlights)
        expected_count = detail.expected_error_count or 0
        highlight_phase_complete = len(cleared_highlights) >= expected_count > 0
        remaining_errors = max(0, expected_count - len(cleared_highlights))

        progress_status = (
            status.progress_status or ProgressStatus.NOT_STARTED.value
        )
        type_hints = self._parse_stored_hallucination_types(detail.hallucination_types)

        return Stage2AssignmentDetailResponse(
            assignment_id=assignment.assignment_id,
            title=assignment.title or "",
            reference_document_text=reference_text,
            question=detail.question or "",
            flawed_ai_response=detail.hallucinated_ai_answer or "",
            expected_error_count=expected_count,
            hallucination_type_options=[
                HallucinationTypeOption(**item) for item in HALLUCINATION_TYPE_OPTIONS
            ],
            hallucination_type_hints=type_hints,
            status=progress_status,
            highlight_phase_complete=highlight_phase_complete,
            remaining_errors_to_find=remaining_errors,
            attempts=Stage2AttemptsDetail(
                max_attempts=max_attempts,
                used_attempts=used_attempts,
                remaining_attempts=remaining,
            ),
            cleared_highlights=cleared_highlights,
        )

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "TEACHER":
            raise Stage2AccessForbiddenError("접근 권한이 없습니다.")
        return user

    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "STUDENT":
            raise Stage2AccessForbiddenError()
        return user

    async def _get_stage2_assignment_for_student(
        self, student: User, assignment_id: int
    ) -> tuple[Assignment, Stage2AssignmentDetail]:
        assignment = await self.assignment_repository.get_by_id(assignment_id)
        if assignment is None or assignment.stage != 2:
            raise AssignmentNotFoundError("존재하지 않는 과제입니다.")
        if student.class_id is None or assignment.class_id != student.class_id:
            raise Stage2AccessForbiddenError()

        detail = await self.stage2_detail_repository.get_by_assignment_id(assignment_id)
        if detail is None:
            raise AssignmentNotFoundError("존재하지 않는 과제입니다.")
        return assignment, detail

    @staticmethod
    def _collect_cleared_highlights(
        highlights: list[Stage2HighlightSubmission],
    ) -> list[str]:
        cleared: list[str] = []
        seen: set[str] = set()
        for row in highlights:
            if not row.is_correct or not row.highlighted_text:
                continue
            text = row.highlighted_text.strip()
            if text and text not in seen:
                seen.add(text)
                cleared.append(text)
        return cleared

    @staticmethod
    def _parse_stored_hallucination_types(raw: list | dict | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(item) for item in raw if item]
        return []

    def _parse_hallucination_types(self, raw: str) -> list[str]:
        stripped = (raw or "").strip()
        if not stripped:
            raise InvalidStage2CreateError()

        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InvalidStage2CreateError() from exc

        if not isinstance(parsed, list) or not parsed:
            raise InvalidStage2CreateError()

        types: list[str] = []
        for item in parsed:
            if not isinstance(item, str):
                raise InvalidStage2CreateError()
            value = item.strip().upper()
            if value not in ALLOWED_HALLUCINATION_TYPES:
                raise InvalidStage2CreateError()
            if value not in types:
                types.append(value)
        return types

    async def _save_upload_file(
        self, assignment_id: int, filename: str, content: bytes
    ) -> Path:
        directory = _UPLOAD_DIR / str(assignment_id)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        path = directory / safe_name
        path.write_bytes(content)
        return path
