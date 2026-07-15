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
    InvalidStage2CreateError,
    InvalidTokenError,
    Stage2AccessForbiddenError,
    Stage2DocumentProcessingError,
    Stage2FileTooLargeError,
    UnsupportedStage2FileTypeError,
)
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.document import DocumentRepository
from app.repositories.stage import Stage2DetailRepository, Stage2ErrorAnswerRepository
from app.repositories.user import UserRepository
from app.schemas.stage2 import (
    ALLOWED_HALLUCINATION_TYPES,
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

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "TEACHER":
            raise Stage2AccessForbiddenError("접근 권한이 없습니다.")
        return user

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
