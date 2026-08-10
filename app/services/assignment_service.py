"""Stage 1 과제 도메인 비즈니스 로직.

검색·context·rag_process_visualization은 백엔드에서 조립하고,
생성(ai_response)은 LangflowClient가 담당한다.
chat은 동일 chunk_size면 DB 청크 임베딩을 재사용하고, temperature는 생성에만 쓴다.
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
    InvalidStage1ParameterError,
    InvalidStage1SubmitError,
    InvalidTokenError,
    Stage1AccessForbiddenError,
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
from app.models.student_status import StudentAssignmentStatus
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
    Stage1AttemptsDetail,
    Stage1AttemptsInfo,
    Stage1ChatRequest,
    Stage1ChatResponse,
    Stage1CreateResponse,
    Stage1EvaluationReport,
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

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf"}
_UPLOAD_DIR = Path("uploads/stage1")


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
        due_at: datetime,
        default_chunk_size: int,
        default_top_k: int,
        default_temperature: float,
        file: UploadFile,
    ) -> Stage1CreateResponse:
        teacher = await self._get_authorized_teacher(user_id)
        allowed_class_ids = await self._get_teacher_class_ids(teacher)
        if class_id not in allowed_class_ids:
            raise Stage1AccessForbiddenError()

        subject = (subject or "").strip()
        filename = (file.filename or "").strip()
        if not subject or not filename:
            raise InvalidStage1CreateError()

        due_at = normalize_assignment_due_at(due_at)
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
            raw_text = extract_text_from_upload(filename, content)
            preset_chunk_sets = await self._embed_preset_chunk_sets(raw_text)
        except UnsupportedStage1FileTypeError:
            raise
        except Stage1DocumentProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("stage1 document processing failed")
            raise Stage1DocumentProcessingError() from exc

        guideline = settings.STAGE1_FIXED_GUIDELINE
        question = await self._generate_student_question(
            raw_text=raw_text,
            subject=subject,
            filename=filename,
        )

        assignment = Assignment(
            teacher_id=teacher.user_id,
            class_id=class_id,
            title="1단계: 파라미터 조절을 통한 환각 완화",
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
            guideline=guideline,
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
            guideline=guideline,
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
        # submit로 기록된 시도만 제출 횟수로 집계 (score가 있는 attempt)
        scored_attempts = [a for a in attempts if a.score is not None]
        used_attempts = len(scored_attempts)
        max_attempts = assignment.max_attempts or settings.STAGE1_MAX_ATTEMPTS
        remaining = (
            status.remaining_attempts
            if status.remaining_attempts is not None
            else max(0, max_attempts - used_attempts)
        )

        highest_score = status.best_score
        best_parameters: Stage1Parameters | None = None
        if scored_attempts:
            best = max(scored_attempts, key=lambda a: float(a.score or 0))
            if highest_score is None and best.score is not None:
                highest_score = int(best.score)
            if best.parameters:
                best_parameters = self._parse_parameters(best.parameters)

        return Stage1AssignmentDetailResponse(
            assignment_id=assignment.assignment_id,
            question=detail.question or "",
            guideline=detail.guideline or "",
            due_at=assignment.due_at,
            parameter_explanations=PARAMETER_EXPLANATIONS,
            default_parameters=default_params,
            attempts=Stage1AttemptsDetail(
                max_attempts=max_attempts,
                used_attempts=used_attempts,
                remaining_attempts=remaining,
            ),
            highest_score=highest_score,
            best_parameters=best_parameters,
        )

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
        )

        # temperature는 생성 단계에만 사용 (검색·임베딩과 분리)
        ai_response = await self.langflow_client.run_stage1_chat(
            message=payload.message,
            context=context,
            temperature=params.temperature,
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

        if not payload.selected_ai_response.strip():
            raise InvalidStage1SubmitError()
        if not payload.student_prompt.strip():
            raise InvalidStage1SubmitError()

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

        documents = await self.document_repository.get_by_assignment_id(assignment_id)
        if not documents or not documents[0].raw_text:
            raise AssignmentNotFoundError("과제 문서가 아직 준비되지 않았습니다.")
        document = documents[0]

        # 전체 원문이 아니라 제출 파라미터로 다시 검색한 청크만 채점 기준에 쓴다.
        # (긴 교재 전체와 겹치면 나쁜 파라미터 답도 100점이 나오던 문제 방지)
        default_params = self._parse_parameters(detail.default_parameters)
        chunk_vectors = await self._load_or_build_chunk_vectors(
            document,
            requested_chunk_size=params.chunk_size,
            default_chunk_size=default_params.chunk_size,
        )
        retrieved_context, _visualization = await self._search_context(
            chunk_vectors,
            message=payload.student_prompt,
            top_k=params.top_k,
        )
        source_text = (retrieved_context or "").strip() or (document.raw_text or "")[:2000]
        report, quality_score = await self._evaluate_response(
            selected_ai_response=payload.selected_ai_response,
            source_text=source_text,
            question=assignment.description or "",
        )
        movement = self._parameter_movement(
            baseline=default_params,
            submitted=params,
        )
        current_score = self._apply_movement_to_score(quality_score, movement)

        # records 대표 제출: 이전 final 해제 후 이번 제출만 is_final=True
        await self.submission_repository.clear_final_for_user_and_assignment(
            student.user_id, assignment_id
        )
        submission = Submission(
            user_id=student.user_id,
            assignment_id=assignment_id,
            stage=1,
            submitted_answer=payload.selected_ai_response,
            final_parameters=params.model_dump(),
            current_score=current_score,
            is_final=True,
        )
        submission = await self.submission_repository.create(submission)

        attempt_number = used + 1
        attempt = Stage1Attempt(
            user_id=student.user_id,
            assignment_id=assignment_id,
            submission_id=submission.submission_id,
            student_prompt=payload.student_prompt,
            ai_response=payload.selected_ai_response,
            attempt_number=attempt_number,
            temperature=Decimal(str(params.temperature)),
            parameters=params.model_dump(),
            score=Decimal(str(current_score)),
        )
        await self.attempt_repository.create(attempt)

        evaluation = Evaluation(
            submission_id=submission.submission_id,
            factuality_score=report.faithfulness_score,
            relevance_score=report.relevance_score,
            feedback=report.feedback,
            evaluation_metadata={
                "faithfulness_score": report.faithfulness_score,
                "relevance_score": report.relevance_score,
                "quality_score": quality_score,
                "parameter_movement": round(movement, 4),
                "movement_lambda": settings.STAGE1_MOVEMENT_LAMBDA,
            },
        )
        await self.evaluation_repository.create(evaluation)

        previous_best = status.best_score
        is_highest = previous_best is None or current_score > previous_best
        new_best = current_score if is_highest else (previous_best or current_score)
        remaining = max(0, max_attempts - attempt_number)

        await self.status_repository.update_progress(
            status,
            progress_status=(
                ProgressStatus.COMPLETED.value
                if remaining == 0
                else ProgressStatus.IN_PROGRESS.value
            ),
            best_score=new_best,
            remaining_attempts=remaining,
        )
        await self.session.commit()

        return Stage1SubmitResponse(
            current_score=current_score,
            highest_score=new_best,
            is_highest_score=is_highest,
            evaluation_report=report,
            attempts=Stage1AttemptsInfo(
                used_attempts=attempt_number,
                remaining_attempts=remaining,
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
        """preset chunk_size마다 청킹 후 임베딩한다. 동시성은 최대 2로 제한."""

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
        """저장된 청크 중 요청 chunk_size와 맞는 벡터만 골라 재사용한다.

        - metadata.chunk_size == 요청값
        - metadata에 chunk_size가 없으면 default_chunk_size == 요청값일 때 허용
        """

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
        """동일 chunk_size면 DB 임베딩 재사용, 다르면 실시간 청킹·임베딩."""

        stored = await self.chunk_repository.get_by_document_id(document.document_id)
        reused = self._reusable_chunk_vectors_from_db(
            stored,
            requested_chunk_size=requested_chunk_size,
            default_chunk_size=default_chunk_size,
        )
        if reused is not None:
            logger.debug(
                "stage1 chat: reusing %s stored chunks (chunk_size=%s)",
                len(reused),
                requested_chunk_size,
            )
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
    ) -> tuple[str, RagProcessVisualization]:
        """질문 임베딩 + cosine 정렬 후 top_k context/visualization 조립.

        temperature는 사용하지 않는다.
        """

        query_embedding = await embed_text(message)
        ranked: list[tuple[float, str]] = []
        for text, emb in chunk_vectors:
            score = cosine_similarity(query_embedding, emb)
            ranked.append((score, text))
        ranked.sort(key=lambda item: item[0], reverse=True)

        selected = ranked[:top_k]
        previews = [text.strip() for _, text in selected if text.strip()]
        context = "\n\n".join(previews)
        best_score = selected[0][0] if selected else 0.0
        visualization = RagProcessVisualization(
            total_chunks=len(chunk_vectors),
            retrieved_chunks=len(selected),
            vector_search_score=round(best_score, 4),
            retrieved_chunk_previews=previews,
        )
        return context, visualization

    async def _evaluate_response(
        self,
        *,
        selected_ai_response: str,
        source_text: str,
        question: str = "",
    ) -> tuple[Stage1EvaluationReport, int]:
        """하이브리드 채점(C).

        1) 원문 토큰 겹침으로 faithfulness / relevance 점수 산출
        2) OpenAI로 학습용 feedback 문장 생성 (키 없거나 실패 시 템플릿 fallback)
        """

        faithfulness, relevance, current_score, template_feedback = (
            self._score_against_source(
                selected_ai_response=selected_ai_response,
                source_text=source_text,
            )
        )
        feedback = await self._generate_ai_feedback(
            question=question,
            selected_ai_response=selected_ai_response,
            source_text=source_text,
            faithfulness=faithfulness,
            relevance=relevance,
            fallback=template_feedback,
        )
        report = Stage1EvaluationReport(
            faithfulness_score=faithfulness,
            relevance_score=relevance,
            feedback=feedback,
        )
        return report, current_score

    def _score_against_source(
        self, *, selected_ai_response: str, source_text: str
    ) -> tuple[int, int, int, str]:
        """원문(제출 시 검색 청크) 토큰 겹침 채점.

        - support = (답변∩기준텍스트) / 답변 토큰 수
        - 기준텍스트는 전체 교재가 아니라 제출 파라미터로 검색한 청크
        - 답변 토큰의 약 55%가 기준에 있으면 100점 근접
        """

        response_tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", selected_ai_response))
        source_tokens = set(re.findall(r"[가-힣A-Za-z0-9]{2,}", source_text))
        if not response_tokens:
            return (
                1,
                1,
                20,
                "답변 내용이 거의 없어 평가가 어렵습니다. 자료에 근거한 설명을 더 채워보세요.",
            )

        overlap = response_tokens & source_tokens
        support = len(overlap) / max(len(response_tokens), 1)

        # 55% support ≈ 100점 (의역 여유). 검색 청크가 짧으면 환각 답은 자연히 낮아짐.
        full_marks_at = 0.55
        normalized = min(1.0, support / full_marks_at) if full_marks_at else 0.0
        current_score = int(round(100 * normalized))
        current_score = max(0, min(100, current_score))

        # API 리포트용 1~5 (동일 스케일에서 환산)
        faithfulness = max(1, min(5, int(round(normalized * 5)) or 1))
        relevance = faithfulness

        if faithfulness <= 2:
            feedback = (
                "답변에 학습 자료에서 확인하기 어려운 내용이 섞여 있는 것 같습니다. "
                "자료에 더 잘 맞는 답을 얻으려면 검색·생성 설정을 다시 살펴보세요."
            )
        elif faithfulness >= 4:
            feedback = (
                "답변이 주어진 자료와 잘 맞아 보입니다. "
                "어떤 설정에서 이런 결과가 나왔는지 스스로 정리해 두면 좋습니다."
            )
        else:
            feedback = (
                "핵심은 대체로 닿아 있지만, 자료와 어긋나거나 애매한 표현이 일부 있습니다. "
                "설정을 바꿔 가며 자료에 더 가까운 답을 비교해 보세요."
            )
        return faithfulness, relevance, current_score, feedback

    def _parameter_movement(
        self,
        *,
        baseline: Stage1Parameters,
        submitted: Stage1Parameters,
    ) -> float:
        """과제 기본 파라미터 대비 제출 파라미터의 변경량 (0~1).

        chunk_size·top_k 비중을 크게, temperature는 작게 반영한다.
        """

        presets = list(settings.STAGE1_CHUNK_SIZE_PRESETS)

        def _chunk_index(size: int) -> int:
            if size in presets:
                return presets.index(size)
            return min(range(len(presets)), key=lambda i: abs(presets[i] - size))

        chunk_span = max(len(presets) - 1, 1)
        chunk_m = abs(_chunk_index(submitted.chunk_size) - _chunk_index(baseline.chunk_size)) / chunk_span
        # UI에서 주로 쓰는 1~10 구간을 기준으로 정규화 (그 이상은 1로 캡)
        topk_m = min(1.0, abs(submitted.top_k - baseline.top_k) / 9.0)
        temp_m = min(1.0, abs(float(submitted.temperature) - float(baseline.temperature)))
        movement = 0.45 * chunk_m + 0.40 * topk_m + 0.15 * temp_m
        return max(0.0, min(1.0, movement))

    def _apply_movement_to_score(self, quality_score: int, movement: float) -> int:
        """최종 = 품질 × (1 − λ × 움직임). 같은 품질이면 덜 바꾼 쪽이 더 높다."""

        lam = float(settings.STAGE1_MOVEMENT_LAMBDA)
        final = quality_score * (1.0 - lam * movement)
        return max(0, min(100, int(round(final))))

    async def _generate_student_question(
        self,
        *,
        raw_text: str,
        subject: str,
        filename: str,
    ) -> str:
        """업로드 문서에서 학생이 볼 '문제(미션)' 문장을 생성한다."""
        fallback = settings.STAGE1_QUESTION_FALLBACK
        if not settings.OPENAI_API_KEY:
            return fallback

        preview = (raw_text or "").strip()[:2500]
        if not preview:
            return fallback

        prompt = (
            "중·고등학생 AI 리터러시 수업용 1단계 과제입니다.\n"
            "학생이 AI에게 질문하고 chunk_size·top_k·temperature를 조절해 "
            "업로드 자료에 맞는 답을 찾는 활동입니다.\n"
            "아래 학습 자료 일부를 읽고, 학생 화면에 보여줄 '문제(미션)'를 "
            "한국어 1~2문장으로 작성하세요.\n"
            "규칙:\n"
            "- 학생이 AI 채팅창에 그대로 칠 '채팅 질문'을 쓰지 마세요.\n"
            "- '~에 대해 AI에게 질문하고, 파라미터를 조절하여 … 찾아보세요' 형태의 미션으로 쓰세요.\n"
            "- 자료의 학습 주제(단원·핵심 개념)를 자연스럽게 넣으세요.\n"
            "- 따옴표·번호·제목 없이 문장만 출력하세요.\n\n"
            f"교과 코드: {subject}\n"
            f"파일명: {filename}\n"
            f"자료 일부:\n{preview}\n"
        )

        try:
            import httpx

            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.OPENAI_CHAT_MODEL,
                        "temperature": 0.4,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "당신은 교사 보조 AI입니다. "
                                    "학생용 과제 미션 문장만 간결하게 출력하세요."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
                .strip('"')
                .strip("'")
            )
            if not content:
                return fallback
            # 한 줄로 정리
            content = re.sub(r"\s+", " ", content)
            return content[:400]
        except Exception:  # noqa: BLE001
            logger.exception("stage1 student question generation failed; using fallback")
            return fallback

    async def _generate_ai_feedback(
        self,
        *,
        question: str,
        selected_ai_response: str,
        source_text: str,
        faithfulness: int,
        relevance: int,
        fallback: str,
    ) -> str:
        if not settings.OPENAI_API_KEY:
            return fallback

        source_preview = (source_text or "")[:1800]
        answer_preview = (selected_ai_response or "")[:1200]
        prompt = (
            "당신은 AI 리터러시 교육용 채점 조교입니다. "
            "학생이 설정을 바꿔 가며 문서 기반 답을 찾는 과제입니다.\n"
            "아래 점수(1~5)와 참고 자료·답변을 보고, 한국어로 2~3문장 피드백하세요.\n"
            "규칙:\n"
            "- 답변이 자료와 얼마나 맞는지, 어떤 점이 아쉬운지만 간접적으로 말해 주세요.\n"
            "- chunk_size, top_k, temperature 등 파라미터 이름을 쓰지 마세요.\n"
            "- '높여라/낮춰라/늘려라/줄여라'처럼 구체적 조절 지시를 하지 마세요.\n"
            "- 숫자 점수만 반복하지 마세요.\n\n"
            f"질문: {question or '(없음)'}\n"
            f"faithfulness(원문 충실): {faithfulness}/5\n"
            f"relevance(관련성): {relevance}/5\n"
            f"참고 자료 일부:\n{source_preview}\n\n"
            f"학생 선택 답변:\n{answer_preview}\n"
        )

        try:
            import httpx

            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.OPENAI_CHAT_MODEL,
                        "temperature": 0.3,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "한국어로 짧고 친절한 학습 피드백만 출력하세요. "
                                    "파라미터 이름이나 높임/낮춤 지시는 하지 마세요."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                response.raise_for_status()
                data = response.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            return content or fallback
        except Exception:  # noqa: BLE001
            logger.exception("stage1 AI feedback generation failed; using template")
            return fallback
