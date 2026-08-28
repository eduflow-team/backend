"""Stage 1 과제 도메인 비즈니스 로직.

교사: PDF 업로드 + 퀴즈 1문제·정답 1개.
학생: 자유 채팅으로 근거 탐색 후 본인 답안 제출.
채점: 정답점수(0|100) − default 대비 리소스 감점(최대 ~30). temperature 감점 없음.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.langflow_client import LangflowClient
from app.core.config import settings
from app.core.datetime_utils import normalize_assignment_due_at
from app.core.exceptions import (
    AssignmentNotFoundError,
    InvalidStage1CreateError,
    InvalidStage1FinalizeError,
    InvalidStage1ParameterError,
    InvalidStage1SubmitError,
    InvalidTokenError,
    Stage1AccessForbiddenError,
    Stage1AlreadyFinalizedError,
    Stage1DocumentNotFoundError,
    Stage1DocumentProcessingError,
    Stage1FileTooLargeError,
    Stage1SubmitLimitExceededError,
    UnsupportedStage1FileTypeError,
)
from app.models.assignment import Assignment
from app.models.document import Document, DocumentChunk
from app.models.enums import ProgressStatus
from app.models.evaluation import Evaluation
from app.models.stage import Stage1AssignmentDetail
from app.models.submission import Stage1Attempt, Submission
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.chunk import DocumentChunkRepository
from app.repositories.class_ import ClassRepository
from app.repositories.document import DocumentRepository
from app.repositories.evaluation import EvaluationRepository
from app.repositories.stage import Stage1AttemptRepository, Stage1DetailRepository
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.submission import SubmissionRepository
from app.repositories.user import UserRepository
from app.schemas.assignments import (
    PARAMETER_EXPLANATIONS,
    RagProcessVisualization,
    Stage1AssignmentDetailResponse,
    Stage1AttemptSummary,
    Stage1AttemptsDetail,
    Stage1AttemptsInfo,
    Stage1ChatRequest,
    Stage1ChatResponse,
    Stage1CreateResponse,
    Stage1EvaluationReport,
    Stage1FinalizeRequest,
    Stage1FinalizeResponse,
    Stage1Parameters,
    Stage1SubmitRequest,
    Stage1SubmitResponse,
)
from app.services.embedding_service import (
    cosine_similarity,
    embed_text,
    embed_texts,
    extract_text_from_upload,
    split_text_into_chunks,
)
from app.services.stage1_context import (
    build_stage1_langflow_pack,
    enforce_stage1_weak_hallucination,
    format_stage1_topk_sentences,
    is_stage1_weak_retrieval,
    redact_stage1_answer_leak,
)

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf"}
_UPLOAD_DIR = Path("uploads/stage1")
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DOCUMENT_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
}


class AssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.stage1_detail_repository = Stage1DetailRepository(session)
        self.document_repository = DocumentRepository(session)
        self.chunk_repository = DocumentChunkRepository(session)
        self.status_repository = StudentAssignmentStatusRepository(session)
        self.attempt_repository = Stage1AttemptRepository(session)
        self.submission_repository = SubmissionRepository(session)
        self.evaluation_repository = EvaluationRepository(session)
        self.langflow_client = LangflowClient()

    # ------------------------------------------------------------------
    # Teacher: create
    # ------------------------------------------------------------------

    async def create_step1_assignment(
        self,
        user_id: int,
        *,
        class_id: int,
        subject: str,
        question: str,
        answer: str,
        due_at: datetime,
        file: UploadFile,
    ) -> Stage1CreateResponse:
        teacher = await self._get_authorized_teacher(user_id)
        allowed_class_ids = await self._get_teacher_class_ids(teacher)
        if class_id not in allowed_class_ids:
            raise Stage1AccessForbiddenError()

        subject = (subject or "").strip()
        question = (question or "").strip()
        answer = (answer or "").strip()
        filename = (file.filename or "").strip()
        if not subject or not filename or not question or not answer:
            raise InvalidStage1CreateError()

        due_at = normalize_assignment_due_at(due_at)
        default_chunk_size = settings.STAGE1_DEFAULT_CHUNK_SIZE
        default_top_k = settings.STAGE1_DEFAULT_TOP_K
        default_temperature = settings.STAGE1_DEFAULT_TEMPERATURE
        self._validate_parameters(default_chunk_size, default_top_k, default_temperature)

        suffix = Path(filename).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise UnsupportedStage1FileTypeError()

        content = await file.read()
        if not content:
            raise InvalidStage1CreateError()
        if len(content) > settings.STAGE1_MAX_UPLOAD_BYTES:
            raise Stage1FileTooLargeError()

        try:
            raw_text = await asyncio.to_thread(
                extract_text_from_upload, filename, content
            )
            preset_chunk_sets = await self._embed_preset_chunk_sets(raw_text)
        except UnsupportedStage1FileTypeError:
            raise
        except Stage1DocumentProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("stage1 document processing failed")
            raise Stage1DocumentProcessingError() from exc

        assignment = Assignment(
            teacher_id=teacher.user_id,
            class_id=class_id,
            title="1단계: 파라미터로 과제 문제 풀기",
            stage=1,
            subject=subject,
            description=question,
            due_at=due_at,
            max_attempts=settings.STAGE1_MAX_ATTEMPTS,
        )
        assignment = await self.assignment_repository.create(assignment)

        default_parameters = {
            "chunk_size": default_chunk_size,
            "top_k": default_top_k,
            "temperature": default_temperature,
        }
        detail = Stage1AssignmentDetail(
            assignment_id=assignment.assignment_id,
            question=question,
            answer=answer,
            default_parameters=default_parameters,
            parameter_guide=PARAMETER_EXPLANATIONS.model_dump(),
        )
        await self.stage1_detail_repository.create(detail)

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

        chunk_rows: list[DocumentChunk] = []
        for chunk_size, pairs in preset_chunk_sets:
            for index, (chunk_text, embedding) in enumerate(pairs):
                chunk_rows.append(
                    DocumentChunk(
                        document_id=document.document_id,
                        content=chunk_text,
                        chunk_index=index,
                        chunk_metadata={"chunk_size": chunk_size},
                        embedding=embedding,
                    )
                )
        await self.chunk_repository.bulk_create(chunk_rows)
        await self.session.commit()

        return Stage1CreateResponse(
            assignment_id=assignment.assignment_id,
            created_at=assignment.created_at or datetime.now(UTC),
            due_at=assignment.due_at,
            question=question,
        )

    # ------------------------------------------------------------------
    # Student: detail
    # ------------------------------------------------------------------

    async def get_step1_assignment(
        self, user_id: int, assignment_id: int
    ) -> Stage1AssignmentDetailResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage1_assignment_for_student(
            student, assignment_id
        )

        default_params = self._parse_parameters(detail.default_parameters)
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=assignment.max_attempts or settings.STAGE1_MAX_ATTEMPTS,
        )
        await self.session.commit()

        attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        scored_attempts = [a for a in attempts if a.score is not None]
        used_attempts = len(scored_attempts)
        max_attempts = assignment.max_attempts or settings.STAGE1_MAX_ATTEMPTS
        remaining = (
            status.remaining_attempts
            if status.remaining_attempts is not None
            else max(0, max_attempts - used_attempts)
        )

        final_submission = await self.submission_repository.get_final_by_user_and_assignment(
            student.user_id, assignment_id
        )
        is_finalized = final_submission is not None or (
            status.progress_status == ProgressStatus.COMPLETED.value
        )
        attempt_summaries = await self._build_attempt_summaries(
            scored_attempts, final_submission_id=final_submission.submission_id if final_submission else None
        )
        final_attempt_number = next(
            (s.attempt_number for s in attempt_summaries if s.is_final), None
        )

        highest_score = status.best_score
        best_parameters: Stage1Parameters | None = None
        if final_attempt_number is not None:
            chosen = next(
                (s for s in attempt_summaries if s.attempt_number == final_attempt_number),
                None,
            )
            if chosen is not None:
                highest_score = chosen.score
                best_parameters = chosen.parameters
        elif scored_attempts:
            best = max(scored_attempts, key=lambda a: float(a.score or 0))
            if highest_score is None and best.score is not None:
                highest_score = int(best.score)
            if best.parameters:
                best_parameters = self._parse_parameters(best.parameters)

        documents = await self.document_repository.get_by_assignment_id(assignment_id)
        document_filename: str | None = None
        document_url: str | None = None
        document_text: str | None = None
        if documents:
            document_filename = documents[0].filename
            document_url = self._step1_document_url(assignment_id)
            raw = documents[0].raw_text or ""
            limit = settings.STAGE1_DOCUMENT_TEXT_MAX_CHARS
            document_text = raw[:limit] if raw else None

        revealed = self._is_answer_revealed(assignment.due_at)
        return Stage1AssignmentDetailResponse(
            assignment_id=assignment.assignment_id,
            question=detail.question or "",
            due_at=assignment.due_at,
            parameter_explanations=PARAMETER_EXPLANATIONS,
            default_parameters=default_params,
            attempts=Stage1AttemptsDetail(
                max_attempts=max_attempts,
                used_attempts=used_attempts,
                remaining_attempts=remaining,
            ),
            attempt_summaries=attempt_summaries,
            is_finalized=is_finalized,
            final_attempt_number=final_attempt_number,
            highest_score=highest_score,
            best_parameters=best_parameters,
            document_filename=document_filename,
            document_url=document_url,
            document_text=document_text,
            is_answer_revealed=revealed,
            correct_answer=(detail.answer if revealed else None),
        )

    async def get_step1_document(
        self, user_id: int, assignment_id: int
    ) -> tuple[Path, str, str]:
        """학생용 학습 자료 원본 파일 경로·파일명·media type."""
        student = await self._get_authorized_student(user_id)
        await self._get_stage1_assignment_for_student(student, assignment_id)
        documents = await self.document_repository.get_by_assignment_id(assignment_id)
        if not documents:
            raise Stage1DocumentNotFoundError()
        return self._resolve_document_file(documents[0])

    # ------------------------------------------------------------------
    # Student: chat
    # ------------------------------------------------------------------

    async def chat_step1(
        self, user_id: int, assignment_id: int, payload: Stage1ChatRequest
    ) -> Stage1ChatResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage1_assignment_for_student(
            student, assignment_id
        )
        params = payload.parameters
        self._validate_parameters(params.chunk_size, params.top_k, params.temperature)

        documents = await self.document_repository.get_by_assignment_id(assignment_id)
        if not documents or not documents[0].raw_text:
            raise AssignmentNotFoundError("과제 문서가 아직 준비되지 않았습니다.")
        document = documents[0]

        default_params = self._parse_parameters(detail.default_parameters)
        chunk_vectors = await self._load_or_build_chunk_vectors(
            document,
            requested_chunk_size=params.chunk_size,
            default_chunk_size=default_params.chunk_size,
        )
        context, visualization = await self._search_context(
            chunk_vectors,
            message=payload.message,
            top_k=params.top_k,
            chunk_size=params.chunk_size,
            document_text=document.raw_text or "",
        )

        # UI preview는 실제 검색 청크만. Langflow용 context만 WEAK/STRONG 래핑.
        mode = (
            "WEAK"
            if is_stage1_weak_retrieval(
                approx_context_chars=visualization.approx_context_chars,
                vector_search_score=visualization.vector_search_score,
                chunk_size=params.chunk_size,
                top_k=params.top_k,
            )
            else "STRONG"
        )
        pack = build_stage1_langflow_pack(context, mode=mode)
        # WEAK일 때는 창의적으로 빗나가게 temperature 하한을 둔다.
        chat_temperature = (
            max(float(params.temperature), 0.95) if mode == "WEAK" else params.temperature
        )

        ai_response = await self.langflow_client.run_stage1_chat(
            message=payload.message,
            context=pack.context,
            temperature=chat_temperature,
        )
        if mode == "WEAK":
            ai_response = enforce_stage1_weak_hallucination(
                ai_response,
                planted_noises=pack.planted_noises,
                correct_answer=detail.answer or "",
            )
        ai_response = redact_stage1_answer_leak(
            ai_response, detail.answer or ""
        )

        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=assignment.max_attempts or settings.STAGE1_MAX_ATTEMPTS,
        )
        if status.progress_status == ProgressStatus.NOT_STARTED.value:
            await self.status_repository.update_progress(
                status, progress_status=ProgressStatus.IN_PROGRESS.value
            )

        await self.session.commit()
        return Stage1ChatResponse(
            ai_response=ai_response,
            rag_process_visualization=visualization,
        )

    # ------------------------------------------------------------------
    # Student: submit
    # ------------------------------------------------------------------

    async def submit_step1(
        self, user_id: int, assignment_id: int, payload: Stage1SubmitRequest
    ) -> Stage1SubmitResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage1_assignment_for_student(
            student, assignment_id
        )
        params = payload.final_parameters
        self._validate_parameters(params.chunk_size, params.top_k, params.temperature)

        student_answer = payload.student_answer.strip()
        if not student_answer:
            raise InvalidStage1SubmitError()
        correct_answer = (detail.answer or "").strip()
        if not correct_answer:
            raise AssignmentNotFoundError("과제 정답이 설정되지 않았습니다.")

        max_attempts = assignment.max_attempts or settings.STAGE1_MAX_ATTEMPTS
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )
        prior_attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        scored = [a for a in prior_attempts if a.score is not None]
        used = len(scored)
        if used >= max_attempts:
            raise Stage1SubmitLimitExceededError()

        existing_final = await self.submission_repository.get_final_by_user_and_assignment(
            student.user_id, assignment_id
        )
        if existing_final is not None or status.progress_status == ProgressStatus.COMPLETED.value:
            raise Stage1AlreadyFinalizedError()

        default_params = self._parse_parameters(detail.default_parameters)
        is_correct = self._answers_match(student_answer, correct_answer)
        correct_score = 100 if is_correct else 0
        resource_penalty, penalty_meta = self._resource_penalty_points(
            default=default_params,
            submitted=params,
        )
        current_score = max(0, correct_score - resource_penalty)
        report = self._build_evaluation_report(
            is_correct=is_correct,
            correct_score=correct_score,
            resource_penalty=resource_penalty,
        )

        submission = Submission(
            user_id=student.user_id,
            assignment_id=assignment_id,
            stage=1,
            submitted_answer=student_answer,
            final_parameters=params.model_dump(),
            current_score=current_score,
            is_final=False,
        )
        submission = await self.submission_repository.create(submission)

        attempt_number = used + 1
        attempt = Stage1Attempt(
            user_id=student.user_id,
            assignment_id=assignment_id,
            submission_id=submission.submission_id,
            student_prompt=student_answer,
            ai_response=None,
            attempt_number=attempt_number,
            temperature=Decimal(str(params.temperature)),
            parameters=params.model_dump(),
            score=Decimal(str(current_score)),
        )
        await self.attempt_repository.create(attempt)

        evaluation = Evaluation(
            submission_id=submission.submission_id,
            factuality_score=5 if is_correct else 1,
            relevance_score=5 if is_correct else 1,
            feedback=report.feedback,
            evaluation_metadata={
                "is_correct": is_correct,
                "correct_score": correct_score,
                "resource_penalty": resource_penalty,
                "summary": report.feedback,
                **penalty_meta,
            },
        )
        await self.evaluation_repository.create(evaluation)

        # 정답이면 즉시 최종 확정. 오답이면 1회 더 허용하고,
        # 마지막 기회까지 쓰면 두 제출 중 점수가 높은 쪽으로 확정.
        should_finalize = is_correct or attempt_number >= max_attempts
        final_submission_id: int | None = None
        if should_finalize:
            await self.submission_repository.clear_final_for_user_and_assignment(
                student.user_id, assignment_id
            )
            # flush된 현재 시도 포함해 최고점 선택 (동점이면 나중 시도)
            all_attempts = await self.attempt_repository.list_by_user_and_assignment(
                student.user_id, assignment_id
            )
            scored_all = [a for a in all_attempts if a.score is not None]
            best_attempt = max(
                scored_all,
                key=lambda a: (float(a.score or 0), int(a.attempt_number or 0)),
            )
            if best_attempt.submission_id == submission.submission_id:
                submission.is_final = True
                await self.submission_repository.update(submission)
                final_submission_id = submission.submission_id
            elif best_attempt.submission_id is not None:
                best_submission = await self.submission_repository.get_by_id(
                    best_attempt.submission_id
                )
                if best_submission is None:
                    submission.is_final = True
                    await self.submission_repository.update(submission)
                    final_submission_id = submission.submission_id
                    best_attempt = attempt
                else:
                    best_submission.is_final = True
                    await self.submission_repository.update(best_submission)
                    final_submission_id = best_submission.submission_id
            else:
                submission.is_final = True
                await self.submission_repository.update(submission)
                final_submission_id = submission.submission_id

            remaining = 0
            new_best = int(best_attempt.score or current_score)
            is_highest = new_best >= current_score
            progress = ProgressStatus.COMPLETED.value
        else:
            previous_best = status.best_score
            is_highest = previous_best is None or current_score > previous_best
            new_best = current_score if is_highest else (previous_best or current_score)
            remaining = max(0, max_attempts - attempt_number)
            progress = ProgressStatus.IN_PROGRESS.value

        await self.status_repository.update_progress(
            status,
            progress_status=progress,
            best_score=new_best,
            remaining_attempts=remaining,
        )
        await self.session.commit()

        all_attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        scored_all = [a for a in all_attempts if a.score is not None]
        attempt_summaries = await self._build_attempt_summaries(
            scored_all,
            final_submission_id=final_submission_id,
        )

        revealed = self._is_answer_revealed(assignment.due_at)
        return Stage1SubmitResponse(
            current_score=current_score,
            highest_score=new_best,
            is_highest_score=is_highest,
            is_correct=is_correct,
            evaluation_report=report,
            attempts=Stage1AttemptsInfo(
                used_attempts=attempt_number,
                remaining_attempts=remaining,
            ),
            attempt_summaries=attempt_summaries,
            is_finalized=should_finalize,
            correct_answer=(correct_answer if revealed else None),
        )

    async def finalize_step1(
        self, user_id: int, assignment_id: int, payload: Stage1FinalizeRequest
    ) -> Stage1FinalizeResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage1_assignment_for_student(
            student, assignment_id
        )
        max_attempts = assignment.max_attempts or settings.STAGE1_MAX_ATTEMPTS
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )

        existing_final = await self.submission_repository.get_final_by_user_and_assignment(
            student.user_id, assignment_id
        )
        if existing_final is not None or status.progress_status == ProgressStatus.COMPLETED.value:
            raise Stage1AlreadyFinalizedError()

        attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        scored = [a for a in attempts if a.score is not None]
        if not scored:
            raise InvalidStage1FinalizeError("채점된 제출이 없습니다. 먼저 답안을 제출해 주세요.")

        chosen = next(
            (
                a
                for a in scored
                if a.attempt_number == payload.attempt_number and a.submission_id is not None
            ),
            None,
        )
        if chosen is None or chosen.submission_id is None:
            raise InvalidStage1FinalizeError()

        submission = await self.submission_repository.get_by_id(chosen.submission_id)
        if submission is None:
            raise InvalidStage1FinalizeError()

        await self.submission_repository.clear_final_for_user_and_assignment(
            student.user_id, assignment_id
        )
        submission.is_final = True
        await self.submission_repository.update(submission)

        chosen_score = int(chosen.score or 0)
        used = len(scored)
        remaining = (
            status.remaining_attempts
            if status.remaining_attempts is not None
            else max(0, max_attempts - used)
        )

        await self.status_repository.update_progress(
            status,
            progress_status=ProgressStatus.COMPLETED.value,
            best_score=chosen_score,
            remaining_attempts=remaining,
        )
        await self.session.commit()

        evaluation = await self.evaluation_repository.get_by_submission_id(
            chosen.submission_id
        )
        meta = evaluation.evaluation_metadata if evaluation else {}
        is_correct = bool(meta.get("is_correct")) if meta else chosen_score > 0
        correct_score = int(meta.get("correct_score", 100 if is_correct else 0)) if meta else (
            100 if is_correct else 0
        )
        resource_penalty = int(meta.get("resource_penalty", 0)) if meta else 0
        feedback = (
            evaluation.feedback
            if evaluation and evaluation.feedback
            else self._build_evaluation_report(
                is_correct=is_correct,
                correct_score=correct_score,
                resource_penalty=resource_penalty,
            ).feedback
        )
        report = Stage1EvaluationReport(
            is_correct=is_correct,
            correct_score=correct_score,
            resource_penalty=resource_penalty,
            feedback=feedback,
        )

        attempt_summaries = await self._build_attempt_summaries(
            scored, final_submission_id=chosen.submission_id
        )
        revealed = self._is_answer_revealed(assignment.due_at)
        correct_answer = (detail.answer or "").strip()
        return Stage1FinalizeResponse(
            attempt_number=int(chosen.attempt_number or payload.attempt_number),
            current_score=chosen_score,
            highest_score=chosen_score,
            is_correct=is_correct,
            evaluation_report=report,
            attempts=Stage1AttemptsInfo(
                used_attempts=used,
                remaining_attempts=remaining,
            ),
            attempt_summaries=attempt_summaries,
            is_finalized=True,
            correct_answer=(correct_answer if revealed else None),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _build_attempt_summaries(
        self,
        scored_attempts: list[Stage1Attempt],
        *,
        final_submission_id: int | None = None,
    ) -> list[Stage1AttemptSummary]:
        summaries: list[Stage1AttemptSummary] = []
        for attempt in scored_attempts:
            params = self._parse_parameters(attempt.parameters)
            is_correct = False
            correct_score = 0
            resource_penalty = 0
            feedback = ""
            if attempt.submission_id is not None:
                evaluation = await self.evaluation_repository.get_by_submission_id(
                    attempt.submission_id
                )
                meta = evaluation.evaluation_metadata if evaluation else None
                if meta:
                    is_correct = bool(meta.get("is_correct"))
                    correct_score = int(meta.get("correct_score", 0))
                    resource_penalty = int(meta.get("resource_penalty", 0))
                if evaluation and evaluation.feedback:
                    feedback = evaluation.feedback
                else:
                    feedback = self._build_evaluation_report(
                        is_correct=is_correct,
                        correct_score=correct_score,
                        resource_penalty=resource_penalty,
                    ).feedback
            summaries.append(
                Stage1AttemptSummary(
                    attempt_number=int(attempt.attempt_number or 0),
                    score=int(attempt.score or 0),
                    is_correct=is_correct,
                    correct_score=correct_score,
                    resource_penalty=resource_penalty,
                    feedback=feedback,
                    student_answer=(attempt.student_prompt or "").strip(),
                    parameters=params,
                    is_final=(
                        final_submission_id is not None
                        and attempt.submission_id == final_submission_id
                    ),
                )
            )
        return summaries

    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "STUDENT":
            raise Stage1AccessForbiddenError()
        return user

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "TEACHER":
            raise Stage1AccessForbiddenError("해당 과제를 생성할 권한이 없습니다.")
        return user

    async def _get_teacher_class_ids(self, teacher: User) -> set[int]:
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = {c.class_id for c in classes}
        if teacher.class_id is not None:
            class_ids.add(teacher.class_id)
        return class_ids

    async def _get_stage1_assignment_for_student(
        self, student: User, assignment_id: int
    ) -> tuple[Assignment, Stage1AssignmentDetail]:
        assignment = await self.assignment_repository.get_by_id(assignment_id)
        if assignment is None or assignment.stage != 1:
            raise AssignmentNotFoundError("존재하지 않는 과제입니다.")
        if student.class_id is None or assignment.class_id != student.class_id:
            raise Stage1AccessForbiddenError()

        detail = await self.stage1_detail_repository.get_by_assignment_id(assignment_id)
        if detail is None:
            raise AssignmentNotFoundError("존재하지 않는 과제입니다.")
        return assignment, detail

    def _validate_parameters(
        self, chunk_size: int, top_k: int, temperature: float
    ) -> None:
        presets = settings.STAGE1_CHUNK_SIZE_PRESETS
        if chunk_size not in presets:
            allowed = ", ".join(str(v) for v in presets)
            raise InvalidStage1ParameterError(
                f"chunk_size는 다음 값만 사용할 수 있습니다: {allowed}"
            )
        if not (1 <= top_k <= 50):
            raise InvalidStage1ParameterError()
        if not (0.0 <= temperature <= 1.0):
            raise InvalidStage1ParameterError()

    async def _embed_preset_chunk_sets(
        self, raw_text: str
    ) -> list[tuple[int, list[tuple[str, list[float]]]]]:
        presets = settings.STAGE1_CHUNK_SIZE_PRESETS
        sem = asyncio.Semaphore(2)

        async def _one(size: int) -> tuple[int, list[tuple[str, list[float]]]]:
            async with sem:
                chunks = split_text_into_chunks(raw_text, size)
                if not chunks:
                    raise Stage1DocumentProcessingError()
                embeddings = await embed_texts(chunks)
                return size, list(zip(chunks, embeddings, strict=True))

        return list(await asyncio.gather(*[_one(size) for size in presets]))

    def _parse_parameters(self, raw: dict | None) -> Stage1Parameters:
        if not raw:
            return Stage1Parameters(chunk_size=50, top_k=2, temperature=1.0)
        try:
            return Stage1Parameters(
                chunk_size=int(raw["chunk_size"]),
                top_k=int(raw["top_k"]),
                temperature=float(raw["temperature"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidStage1ParameterError() from exc

    async def _save_upload_file(
        self, assignment_id: int, filename: str, content: bytes
    ) -> Path:
        directory = _UPLOAD_DIR / str(assignment_id)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        path = directory / safe_name
        path.write_bytes(content)
        return path

    @staticmethod
    def _step1_document_url(assignment_id: int) -> str:
        return (
            f"{settings.API_V1_STR.rstrip('/')}/student/assignments/"
            f"{assignment_id}/step1/document"
        )

    @classmethod
    def _resolve_document_file(cls, document: Document) -> tuple[Path, str, str]:
        if not document.file_path:
            raise Stage1DocumentNotFoundError()

        path = Path(document.file_path)
        if not path.is_absolute():
            path = _BACKEND_ROOT / path
        if not path.is_file():
            raise Stage1DocumentNotFoundError()

        filename = Path(document.filename or path.name).name
        suffix = path.suffix.lower()
        media_type = _DOCUMENT_MEDIA_TYPES.get(suffix, "application/octet-stream")
        return path, filename, media_type

    @staticmethod
    def _is_answer_revealed(due_at: datetime | None) -> bool:
        if due_at is None:
            return False
        now = datetime.now(UTC)
        compare = due_at if due_at.tzinfo else due_at.replace(tzinfo=UTC)
        return now >= compare.astimezone(UTC)

    @staticmethod
    def _normalize_answer(text: str) -> str:
        """공백·구두점 정리 후 소문자 비교용 문자열."""
        normalized = (text or "").strip().casefold()
        normalized = re.sub(r"\s+", "", normalized)
        normalized = re.sub(r"[\"'“”‘’.,!?·・/\-––—()\[\]{}]", "", normalized)
        return normalized

    @classmethod
    def _answers_match(cls, student_answer: str, correct_answer: str) -> bool:
        return cls._normalize_answer(student_answer) == cls._normalize_answer(
            correct_answer
        )

    def _resource_penalty_points(
        self,
        *,
        default: Stage1Parameters,
        submitted: Stage1Parameters,
    ) -> tuple[int, dict]:
        """default보다 키운 top_k/chunk만 감점. temperature 제외. 최대 ~30점."""
        presets = list(settings.STAGE1_CHUNK_SIZE_PRESETS)
        try:
            default_idx = presets.index(default.chunk_size)
        except ValueError:
            default_idx = 0
        try:
            submitted_idx = presets.index(submitted.chunk_size)
        except ValueError:
            submitted_idx = default_idx

        k_scale = max(1, int(settings.STAGE1_K_SCALE))
        chunk_scale = max(1, int(settings.STAGE1_CHUNK_SCALE))
        penalty_k = min(1.0, max(0, submitted.top_k - default.top_k) / k_scale)
        penalty_chunk = min(
            1.0, max(0, submitted_idx - default_idx) / chunk_scale
        )
        resource = 100.0 * (
            settings.STAGE1_RESOURCE_TOP_K_WEIGHT * penalty_k
            + settings.STAGE1_RESOURCE_CHUNK_WEIGHT * penalty_chunk
        )
        resource = max(0.0, min(100.0, resource))
        deducted = int(round(settings.STAGE1_RESOURCE_PENALTY_WEIGHT * resource))
        meta = {
            "penalty_k": round(penalty_k, 4),
            "penalty_chunk": round(penalty_chunk, 4),
            "resource_penalty_raw": round(resource, 4),
            "default_parameters": default.model_dump(),
            "submitted_parameters": submitted.model_dump(),
            "k_scale": k_scale,
            "chunk_scale": chunk_scale,
        }
        return deducted, meta

    def _build_evaluation_report(
        self,
        *,
        is_correct: bool,
        correct_score: int,
        resource_penalty: int,
    ) -> Stage1EvaluationReport:
        if is_correct and resource_penalty == 0:
            feedback = "정답입니다. 기본 파라미터 근처에서 잘 해결했습니다."
        elif is_correct and resource_penalty > 0:
            feedback = (
                f"정답입니다. 다만 기본값보다 검색 자원을 많이 써서 "
                f"{resource_penalty}점이 감점되었습니다."
            )
        elif not is_correct and resource_penalty > 0:
            feedback = (
                "오답입니다. 파라미터를 조절해 자료에서 근거를 더 찾아보세요. "
                f"(기본값보다 자원을 많이 써서 {resource_penalty}점도 감점되었습니다.)"
            )
        else:
            feedback = (
                "오답입니다. AI와 대화하며 파라미터를 조절해 "
                "자료에서 근거를 찾아 다시 제출해 보세요."
            )
        return Stage1EvaluationReport(
            is_correct=is_correct,
            correct_score=correct_score,
            resource_penalty=resource_penalty,
            feedback=feedback,
        )

    @staticmethod
    def _chunk_size_from_metadata(metadata: dict | None) -> int | None:
        if not metadata:
            return None
        raw = metadata.get("chunk_size")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_float_vector(embedding: object) -> list[float] | None:
        if embedding is None:
            return None
        try:
            values = [float(x) for x in list(embedding)]
        except (TypeError, ValueError):
            return None
        return values or None

    def _reusable_chunk_vectors_from_db(
        self,
        rows: list[DocumentChunk],
        *,
        requested_chunk_size: int,
        default_chunk_size: int,
    ) -> list[tuple[str, list[float]]] | None:
        matched: list[tuple[str, list[float]]] = []
        for row in rows:
            if not row.content:
                continue
            vector = self._as_float_vector(row.embedding)
            if vector is None:
                continue
            stored_size = self._chunk_size_from_metadata(row.chunk_metadata)
            if stored_size is not None:
                if stored_size != requested_chunk_size:
                    continue
            elif default_chunk_size != requested_chunk_size:
                continue
            matched.append((row.content, vector))

        return matched or None

    async def _load_or_build_chunk_vectors(
        self,
        document: Document,
        *,
        requested_chunk_size: int,
        default_chunk_size: int,
    ) -> list[tuple[str, list[float]]]:
        stored = await self.chunk_repository.get_by_document_id(document.document_id)
        reused = self._reusable_chunk_vectors_from_db(
            stored,
            requested_chunk_size=requested_chunk_size,
            default_chunk_size=default_chunk_size,
        )
        if reused is not None:
            return reused

        raw_text = document.raw_text or ""
        chunks = split_text_into_chunks(raw_text, requested_chunk_size)
        if not chunks:
            raise Stage1DocumentProcessingError()
        embeddings = await embed_texts(chunks)
        return list(zip(chunks, embeddings, strict=True))

    async def _search_context(
        self,
        chunk_vectors: list[tuple[str, list[float]]],
        *,
        message: str,
        top_k: int,
        chunk_size: int,
        document_text: str = "",
    ) -> tuple[str, RagProcessVisualization]:
        query_embedding = await embed_text(message)
        ranked: list[tuple[float, str]] = []
        for text, emb in chunk_vectors:
            score = cosine_similarity(query_embedding, emb)
            ranked.append((score, text))
        ranked.sort(key=lambda item: item[0], reverse=True)

        selected = ranked[:top_k]
        raw_chunks = [text.strip() for _, text in selected if text.strip()]
        # Langflow에는 실제 검색 청크, UI에는 문장처럼 정리한 참고문
        context = "\n\n".join(raw_chunks)
        previews = format_stage1_topk_sentences(raw_chunks, document_text)
        best_score = selected[0][0] if selected else 0.0
        approx_chars = sum(len(p) for p in raw_chunks) or (top_k * chunk_size)
        visualization = RagProcessVisualization(
            total_chunks=len(chunk_vectors),
            retrieved_chunks=len(selected),
            vector_search_score=round(best_score, 4),
            retrieved_chunk_previews=previews,
            approx_context_chars=approx_chars,
        )
        return context, visualization
