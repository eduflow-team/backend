"""Stage 1 과제 도메인 비즈니스 로직.

Langflow HTTP 호출은 AI 총괄 연동 전까지 mock 응답을 반환한다.
검색·context·rag_process_visualization은 백엔드에서 조립한다.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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
        guideline: str,
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
        question = (question or "").strip()
        guideline = (guideline or "").strip()
        filename = (file.filename or "").strip()
        if not subject or not question or not guideline or not filename:
            raise InvalidStage1CreateError()

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
            chunks = split_text_into_chunks(raw_text, default_chunk_size)
            if not chunks:
                raise Stage1DocumentProcessingError()
            embeddings = await embed_texts(chunks)
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
            title="1단계: 파라미터 조절을 통한 환각 완화",
            stage=1,
            subject=subject,
            description=question,
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

        chunk_rows = [
            DocumentChunk(
                document_id=document.document_id,
                content=chunk_text,
                chunk_index=index,
                chunk_metadata={"chunk_size": default_chunk_size},
                embedding=embedding,
            )
            for index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]
        await self.chunk_repository.bulk_create(chunk_rows)
        await self.session.commit()

        return Stage1CreateResponse(
            assignment_id=assignment.assignment_id,
            created_at=assignment.created_at or datetime.now(UTC),
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
        assignment, _detail = await self._get_stage1_assignment_for_student(
            student, assignment_id
        )
        params = payload.parameters
        self._validate_parameters(params.chunk_size, params.top_k, params.temperature)

        documents = await self.document_repository.get_by_assignment_id(assignment_id)
        if not documents or not documents[0].raw_text:
            raise AssignmentNotFoundError("과제 문서가 아직 준비되지 않았습니다.")
        document = documents[0]

        chunks = split_text_into_chunks(document.raw_text, params.chunk_size)
        if not chunks:
            raise Stage1DocumentProcessingError()

        query_embedding = await embed_text(payload.message)
        # top_k가 크지 않으면 전체 청크 임베딩, 너무 많으면 상위 N만 임베딩 후 재랭킹을 단순화
        chunk_embeddings = await embed_texts(chunks)

        ranked: list[tuple[float, str]] = []
        for text, emb in zip(chunks, chunk_embeddings, strict=True):
            score = cosine_similarity(query_embedding, emb)
            ranked.append((score, text))
        ranked.sort(key=lambda item: item[0], reverse=True)

        selected = ranked[: params.top_k]
        context = "\n\n".join(text for _, text in selected)
        best_score = selected[0][0] if selected else 0.0

        visualization = RagProcessVisualization(
            total_chunks=len(chunks),
            retrieved_chunks=len(selected),
            vector_search_score=round(best_score, 4),
        )

        # TODO(AI 총괄): Langflow HTTP client로 message/context/temperature tweaks 연동
        ai_response = self._mock_langflow_response(
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
        assignment, _detail = await self._get_stage1_assignment_for_student(
            student, assignment_id
        )
        params = payload.final_parameters
        self._validate_parameters(params.chunk_size, params.top_k, params.temperature)

        if not payload.selected_ai_response.strip():
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
        source_text = documents[0].raw_text if documents else ""
        report, current_score = await self._evaluate_response(
            selected_ai_response=payload.selected_ai_response,
            source_text=source_text or "",
            question=assignment.description or "",
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
            student_prompt=None,
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
        if not (50 <= chunk_size <= 4000):
            raise InvalidStage1ParameterError()
        if not (1 <= top_k <= 50):
            raise InvalidStage1ParameterError()
        if not (0.0 <= temperature <= 1.0):
            raise InvalidStage1ParameterError()

    def _parse_parameters(self, raw: dict | None) -> Stage1Parameters:
        if not raw:
            return Stage1Parameters(chunk_size=200, top_k=2, temperature=0.9)
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

    def _mock_langflow_response(
        self, *, message: str, context: str, temperature: float
    ) -> str:
        """Langflow 연동 전 placeholder.

        context가 있으면 요약형으로 재작성하고, temperature가 높으면 추측 문장을 덧붙인다.
        """

        snippets = [s.strip() for s in re.split(r"\n{2,}", context) if s.strip()]
        base_parts = snippets[:3] if snippets else ["제공된 학습 자료에서 관련 내용을 찾지 못했습니다."]
        lines = [
            f"질문('{message}')에 대해 검색된 자료를 바탕으로 답변합니다.",
            *base_parts,
        ]
        # 10문장 이상을 맞추기 위한 확장 (체험용 mock)
        fillers = [
            "위 내용은 검색된 청크를 중심으로 정리한 것입니다.",
            "파라미터가 달라지면 검색 범위와 답변 톤도 함께 달라질 수 있습니다.",
            "학습 자료에 나온 사실을 우선적으로 언급했습니다.",
            "학생이 이해하기 쉬운 문장으로 풀어 썼습니다.",
            "추가 질문은 같은 자료 범위에서 다시 검색할 수 있습니다.",
            "자료에 없는 세부 일화는 온도가 높을 때 더 쉽게 섞일 수 있습니다.",
            "실제 운영에서는 Langflow가 이 구간을 생성합니다.",
        ]
        while len(lines) < 10:
            lines.append(fillers[(len(lines) - 1) % len(fillers)])

        if temperature >= 0.7:
            lines.append(
                "참고로 자료에 직접 나오지 않은 배경 이야기도 섞어 설명할 수 있습니다. "
                "(고온 mock)"
            )
        return " ".join(lines)

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
        overlap_ratio = len(overlap) / max(len(response_tokens), 1)
        coverage = len(overlap) / max(len(source_tokens), 1) if source_tokens else 0.0

        faithfulness = max(1, min(5, round(overlap_ratio * 5)))
        relevance = max(
            1,
            min(5, round((0.6 * overlap_ratio + 0.4 * min(1.0, coverage * 20)) * 5)),
        )
        current_score = int(round(((faithfulness + relevance) / 10) * 100))

        if faithfulness <= 2:
            feedback = (
                "질문에서 요구한 핵심 내용은 일부 포함되었으나, 원본 교재에 없는 내용이 섞여 있을 수 "
                "있습니다. AI가 주어진 문서에만 집중하게 만들려면 temperature를 낮추거나 top_k를 "
                "조절해 보세요."
            )
        elif faithfulness >= 4:
            feedback = (
                "검색된 자료와의 일치도가 높고 관련 정보도 잘 담겼습니다. "
                "지금의 파라미터 조합을 기억해 두면 도움이 됩니다."
            )
        else:
            feedback = (
                "핵심 내용은 대체로 맞지만 일부 표현이 자료와 어긋날 수 있습니다. "
                "chunk_size·top_k·temperature를 바꿔 보며 원문에 더 가까운 답을 찾아보세요."
            )
        return faithfulness, relevance, current_score, feedback

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
            "학생이 파라미터(chunk_size, top_k, temperature)를 조절해 문서 기반 답을 찾는 과제입니다.\n"
            "아래 점수(1~5)와 원문·답변을 보고, 학생이 다음에 무엇을 바꿀지 한국어로 2~3문장 피드백하세요. "
            "숫자 점수만 반복하지 말고, temperature/top_k/chunk_size 중 조절 힌트를 포함하세요.\n\n"
            f"질문: {question or '(없음)'}\n"
            f"faithfulness(원문 충실): {faithfulness}/5\n"
            f"relevance(관련성): {relevance}/5\n"
            f"원문 일부:\n{source_preview}\n\n"
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
                                "content": "한국어로 짧고 친절한 학습 피드백만 출력하세요.",
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
