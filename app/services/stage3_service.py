"""Stage 3 관점 비교 토론 과제 비즈니스 로직.

교사는 주제·페르소나를 출제하고, 학생은 토론을 들은 뒤
팩트체커 사용 여부를 제출한다. 점수는 어느 쪽이 이겼느냐가 아니라
검증이 필요한 순간에 AI를 썼는지로 매긴다.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.stage3_langflow_client import Stage3LangflowClient
from app.core.config import settings
from app.core.exceptions import (
    AssignmentNotFoundError,
    InvalidStage3CreateError,
    InvalidStage3SubmitError,
    InvalidTokenError,
    Stage3AccessForbiddenError,
    Stage3AlreadySubmittedError,
    Stage3DebateNotStartedError,
    Stage3SubmitLimitExceededError,
    Stage3TurnNotFoundError,
)
from app.models.assignment import Assignment
from app.models.enums import ProgressStatus
from app.models.evaluation import Evaluation
from app.models.stage import Stage3AssignmentDetail
from app.models.submission import Stage3DebateAttempt, Submission
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.class_ import ClassRepository
from app.repositories.evaluation import EvaluationRepository
from app.repositories.stage import Stage3AttemptRepository, Stage3DetailRepository
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.submission import SubmissionRepository
from app.repositories.user import UserRepository
from app.schemas.stage3 import (
    ALLOWED_DEBATE_MODES,
    Stage3AssignmentDetailResponse,
    Stage3AttemptsDetail,
    Stage3Claim,
    Stage3CreateRequest,
    Stage3CreateResponse,
    Stage3DebatePublicPayload,
    Stage3DebateRequest,
    Stage3DebateResponse,
    Stage3FactcheckRequest,
    Stage3FactcheckResponse,
    Stage3GradeRow,
    Stage3Speaker,
    Stage3SubmitRequest,
    Stage3SubmitResponse,
    Stage3TurnPublic,
)
from app.services.stage3_debate import (
    build_turns,
    grade_usage,
    public_turns,
    resolve_checked_turn_ids,
)

logger = logging.getLogger(__name__)

_DEFAULT_PRO_PERSONA = "효율성을 강조하는 교육 전문가"
_DEFAULT_CON_PERSONA = "개인정보 침해를 우려하는 인권 전문가"
_DEFAULT_FACT_PERSONA = "중립적인 과학 기자"
_DEFAULT_TITLE = "3단계: 관점 비교 토론"


class Stage3Service:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.stage3_detail_repository = Stage3DetailRepository(session)
        self.attempt_repository = Stage3AttemptRepository(session)
        self.status_repository = StudentAssignmentStatusRepository(session)
        self.submission_repository = SubmissionRepository(session)
        self.evaluation_repository = EvaluationRepository(session)
        self.langflow_client = Stage3LangflowClient()

    # ------------------------------------------------------------------
    # Teacher: create
    # ------------------------------------------------------------------

    async def create_step3_assignment(
        self, user_id: int, payload: Stage3CreateRequest
    ) -> Stage3CreateResponse:
        teacher = await self._get_authorized_teacher(user_id)
        allowed_class_ids = await self._get_teacher_class_ids(teacher)
        if payload.class_id not in allowed_class_ids:
            raise Stage3AccessForbiddenError("해당 과제를 생성할 권한이 없습니다.")

        topic = (payload.topic or "").strip()
        pro_persona = (payload.pro_persona or "").strip() or _DEFAULT_PRO_PERSONA
        con_persona = (payload.con_persona or "").strip() or _DEFAULT_CON_PERSONA
        fact_persona = (payload.fact_persona or "").strip() or _DEFAULT_FACT_PERSONA
        debate_mode = (payload.debate_mode or "v2").strip().lower()
        if not topic:
            raise InvalidStage3CreateError()
        if debate_mode not in ALLOWED_DEBATE_MODES:
            raise InvalidStage3CreateError("debate_mode는 v1 또는 v2만 허용됩니다.")
        if len(pro_persona) > 100 or len(con_persona) > 100 or len(fact_persona) > 100:
            raise InvalidStage3CreateError()

        title = (payload.title or "").strip() or _DEFAULT_TITLE
        subject = (payload.subject or "").strip() or None
        parsed_due_at = self._parse_due_at(payload.due_at)

        assignment = Assignment(
            teacher_id=teacher.user_id,
            class_id=payload.class_id,
            title=title,
            stage=3,
            subject=subject,
            description=topic,
            max_attempts=settings.STAGE3_MAX_ATTEMPTS,
            due_at=parsed_due_at,
        )
        assignment = await self.assignment_repository.create(assignment)

        detail = Stage3AssignmentDetail(
            assignment_id=assignment.assignment_id,
            topic=topic,
            question=None,
            pro_persona=pro_persona,
            con_persona=con_persona,
            fact_persona=fact_persona,
            debate_mode=debate_mode,
        )
        await self.stage3_detail_repository.create(detail)
        await self.session.commit()

        return Stage3CreateResponse(
            assignment_id=assignment.assignment_id,
            title=assignment.title,
            topic=topic,
            debate_mode=debate_mode,
            created_at=assignment.created_at,
        )

    # ------------------------------------------------------------------
    # Student: detail
    # ------------------------------------------------------------------

    async def get_step3_assignment(
        self, user_id: int, assignment_id: int
    ) -> Stage3AssignmentDetailResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage3_assignment_for_student(
            student, assignment_id
        )

        max_attempts = assignment.max_attempts or settings.STAGE3_MAX_ATTEMPTS
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )
        attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        in_progress = self._latest_in_progress(attempts)
        used = len(attempts)
        remaining = max(0, max_attempts - used)

        debate = None
        if in_progress is not None:
            debate = self._to_public_debate(
                in_progress.debate_payload or {},
                self._checked_ids(in_progress),
            )

        return Stage3AssignmentDetailResponse(
            assignment_id=assignment.assignment_id,
            title=assignment.title,
            topic=detail.topic,
            question=detail.question,
            pro_persona=detail.pro_persona,
            con_persona=detail.con_persona,
            fact_persona=detail.fact_persona,
            debate_mode=detail.debate_mode or "v2",
            status=status.progress_status or ProgressStatus.NOT_STARTED.value,
            debate_started=in_progress is not None,
            submitted=any(row.score is not None for row in attempts),
            attempts=Stage3AttemptsDetail(
                max_attempts=max_attempts,
                used_attempts=used,
                remaining_attempts=remaining,
            ),
            highest_score=status.best_score,
            due_at=assignment.due_at,
            debate=debate,
        )

    # ------------------------------------------------------------------
    # Student: start / reuse debate
    # ------------------------------------------------------------------

    async def start_debate(
        self,
        user_id: int,
        assignment_id: int,
        payload: Stage3DebateRequest | None = None,
    ) -> Stage3DebateResponse:
        student = await self._get_authorized_student(user_id)
        assignment, detail = await self._get_stage3_assignment_for_student(
            student, assignment_id
        )
        max_attempts = assignment.max_attempts or settings.STAGE3_MAX_ATTEMPTS
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )
        attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        in_progress = self._latest_in_progress(attempts)
        if in_progress is not None:
            remaining = max(0, max_attempts - len(attempts))
            return Stage3DebateResponse(
                assignment_id=assignment_id,
                attempt_id=in_progress.attempt_id,
                attempt_number=in_progress.attempt_number or len(attempts),
                reused=True,
                debate=self._to_public_debate(
                    in_progress.debate_payload or {},
                    self._checked_ids(in_progress),
                ),
                attempts=Stage3AttemptsDetail(
                    max_attempts=max_attempts,
                    used_attempts=len(attempts),
                    remaining_attempts=remaining,
                ),
            )

        if len(attempts) >= max_attempts:
            raise Stage3SubmitLimitExceededError()

        question = (payload.question if payload else None) or detail.question
        langflow_result = await self.langflow_client.run_debate(
            topic=detail.topic,
            pro_persona=detail.pro_persona,
            con_persona=detail.con_persona,
            fact_persona=detail.fact_persona or _DEFAULT_FACT_PERSONA,
            question=question,
            mode=detail.debate_mode or "v2",
        )
        debate_payload = build_turns(
            [
                {"role": "pro", "text": langflow_result.pro_argument},
                {"role": "con", "text": langflow_result.con_argument},
                {"role": "rebut", "text": langflow_result.rebuttal_argument},
            ],
            langflow_result.fact_check,
            topic=detail.topic,
            pro_role=detail.pro_persona,
            con_role=detail.con_persona,
            source=langflow_result.source,
            mode=detail.debate_mode or "v2",
        )
        if not debate_payload.get("turns"):
            raise InvalidStage3SubmitError("에이전트 발언을 받지 못했습니다.")

        attempt_number = len(attempts) + 1
        attempt = Stage3DebateAttempt(
            user_id=student.user_id,
            assignment_id=assignment_id,
            attempt_number=attempt_number,
            debate_payload=debate_payload,
            checked_turn_ids=[],
            score=None,
        )
        attempt = await self.attempt_repository.create(attempt)

        used = attempt_number
        remaining = max(0, max_attempts - used)
        await self.status_repository.update_progress(
            status,
            progress_status=ProgressStatus.IN_PROGRESS.value,
            remaining_attempts=remaining,
        )
        await self.session.commit()

        return Stage3DebateResponse(
            assignment_id=assignment_id,
            attempt_id=attempt.attempt_id,
            attempt_number=attempt_number,
            reused=False,
            debate=self._to_public_debate(debate_payload, set()),
            attempts=Stage3AttemptsDetail(
                max_attempts=max_attempts,
                used_attempts=used,
                remaining_attempts=remaining,
            ),
        )

    # ------------------------------------------------------------------
    # Student: fact-check one turn
    # ------------------------------------------------------------------

    async def factcheck_turn(
        self,
        user_id: int,
        assignment_id: int,
        payload: Stage3FactcheckRequest,
    ) -> Stage3FactcheckResponse:
        student = await self._get_authorized_student(user_id)
        await self._get_stage3_assignment_for_student(student, assignment_id)
        attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        in_progress = self._latest_in_progress(attempts)
        if in_progress is None:
            if attempts:
                raise Stage3AlreadySubmittedError()
            raise Stage3DebateNotStartedError()

        turns = (in_progress.debate_payload or {}).get("turns") or []
        turn = next((item for item in turns if item.get("id") == payload.turn_id), None)
        if turn is None:
            raise Stage3TurnNotFoundError()

        checked = self._checked_ids(in_progress)
        checked.add(payload.turn_id)
        in_progress.checked_turn_ids = sorted(checked)
        await self.attempt_repository.update(in_progress)
        await self.session.commit()

        claims = [
            Stage3Claim(
                claim=str(item.get("claim") or ""),
                verdict=str(item.get("verdict") or "unsupported"),
                reason=str(item.get("reason") or ""),
            )
            for item in (turn.get("claims") or [])
            if isinstance(item, dict)
        ]
        return Stage3FactcheckResponse(
            turn_id=payload.turn_id,
            verdict=str(turn.get("verdict") or "supported"),
            why=str(turn.get("why") or ""),
            claims=claims,
        )

    # ------------------------------------------------------------------
    # Student: submit / grade
    # ------------------------------------------------------------------

    async def submit_step3(
        self,
        user_id: int,
        assignment_id: int,
        payload: Stage3SubmitRequest,
    ) -> Stage3SubmitResponse:
        student = await self._get_authorized_student(user_id)
        assignment, _detail = await self._get_stage3_assignment_for_student(
            student, assignment_id
        )
        max_attempts = assignment.max_attempts or settings.STAGE3_MAX_ATTEMPTS
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )
        attempts = await self.attempt_repository.list_by_user_and_assignment(
            student.user_id, assignment_id
        )
        in_progress = self._latest_in_progress(attempts)
        if in_progress is None:
            if attempts:
                raise Stage3AlreadySubmittedError()
            raise Stage3DebateNotStartedError()

        turns = (in_progress.debate_payload or {}).get("turns") or []
        if not turns:
            raise InvalidStage3SubmitError()

        checked = resolve_checked_turn_ids(
            turns,
            self._checked_ids(in_progress),
            payload.decisions,
        )

        report = grade_usage(turns, checked)
        current_score = int(report["score"])

        await self.submission_repository.clear_final_for_user_and_assignment(
            student.user_id, assignment_id
        )
        submission = Submission(
            user_id=student.user_id,
            assignment_id=assignment_id,
            stage=3,
            submitted_answer=json.dumps(
                {
                    "checked_turn_ids": sorted(checked),
                    "outcomes": [row["outcome"] for row in report["rows"]],
                },
                ensure_ascii=False,
            ),
            final_parameters={
                "mode": (in_progress.debate_payload or {}).get("mode") or "v2",
                "checked_turn_ids": sorted(checked),
            },
            current_score=current_score,
            is_final=True,
        )
        submission = await self.submission_repository.create(submission)

        in_progress.submission_id = submission.submission_id
        in_progress.checked_turn_ids = sorted(checked)
        in_progress.score = current_score
        await self.attempt_repository.update(in_progress)

        evaluation = Evaluation(
            submission_id=submission.submission_id,
            ai_understanding_score=current_score,
            data_literacy_score=current_score,
            total_literacy_score=current_score,
            feedback=f"{report['headline']} {report['advice']}".strip(),
            evaluation_metadata={
                "caught": report["caught"],
                "passed": report["passed"],
                "missed": report["missed"],
                "wasted": report["wasted"],
                "headline": report["headline"],
                "advice": report["advice"],
                "rows": report["rows"],
            },
        )
        await self.evaluation_repository.create(evaluation)

        used = len(attempts)
        remaining = max(0, max_attempts - used)
        previous_best = status.best_score
        is_highest = previous_best is None or current_score > previous_best
        new_best = current_score if is_highest else (previous_best or current_score)
        await self.status_repository.update_progress(
            status,
            progress_status=(
                ProgressStatus.COMPLETED.value
                if remaining == 0
                else ProgressStatus.IN_PROGRESS.value
            ),
            best_score=new_best,
            remaining_attempts=remaining,
            total_literacy_score=new_best,
        )
        await self.session.commit()

        return Stage3SubmitResponse(
            current_score=current_score,
            highest_score=new_best,
            is_highest_score=is_highest,
            caught=report["caught"],
            passed=report["passed"],
            missed=report["missed"],
            wasted=report["wasted"],
            headline=report["headline"],
            advice=report["advice"],
            rows=[Stage3GradeRow(**row) for row in report["rows"]],
            attempts=Stage3AttemptsDetail(
                max_attempts=max_attempts,
                used_attempts=used,
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
            raise Stage3AccessForbiddenError()
        return user

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "TEACHER":
            raise Stage3AccessForbiddenError("해당 과제를 생성할 권한이 없습니다.")
        return user

    async def _get_teacher_class_ids(self, teacher: User) -> set[int]:
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = {item.class_id for item in classes}
        if teacher.class_id is not None:
            class_ids.add(teacher.class_id)
        return class_ids

    async def _get_stage3_assignment_for_student(
        self, student: User, assignment_id: int
    ) -> tuple[Assignment, Stage3AssignmentDetail]:
        assignment = await self.assignment_repository.get_by_id(assignment_id)
        if assignment is None or assignment.stage != 3:
            raise AssignmentNotFoundError("존재하지 않는 과제입니다.")
        if student.class_id is None or assignment.class_id != student.class_id:
            raise Stage3AccessForbiddenError()

        detail = await self.stage3_detail_repository.get_by_assignment_id(assignment_id)
        if detail is None:
            raise AssignmentNotFoundError("존재하지 않는 과제입니다.")
        return assignment, detail

    @staticmethod
    def _latest_in_progress(
        attempts: list[Stage3DebateAttempt],
    ) -> Stage3DebateAttempt | None:
        for attempt in reversed(attempts):
            if attempt.score is None:
                return attempt
        return None

    @staticmethod
    def _checked_ids(attempt: Stage3DebateAttempt) -> set[str]:
        raw = attempt.checked_turn_ids or []
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw if item}

    @staticmethod
    def _to_public_debate(
        payload: dict,
        checked_ids: set[str],
        *,
        reveal_all: bool = False,
    ) -> Stage3DebatePublicPayload:
        pro = payload.get("pro") or {}
        con = payload.get("con") or {}
        turns = public_turns(
            payload.get("turns") or [],
            checked_ids,
            reveal_all=reveal_all,
        )
        return Stage3DebatePublicPayload(
            topic=str(payload.get("topic") or ""),
            source=str(payload.get("source") or "mock"),
            mode=str(payload.get("mode") or "v2"),
            elapsed=payload.get("elapsed"),
            pro=Stage3Speaker(
                name=str(pro.get("name") or "찬성 측 AI"),
                role=str(pro.get("role") or ""),
            ),
            con=Stage3Speaker(
                name=str(con.get("name") or "반대 측 AI"),
                role=str(con.get("role") or ""),
            ),
            turns=[Stage3TurnPublic.model_validate(item) for item in turns],
        )

    @staticmethod
    def _parse_due_at(raw: str | None) -> datetime | None:
        if not raw or not str(raw).strip():
            return None
        text = str(raw).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise InvalidStage3CreateError("마감 시각 형식이 올바르지 않습니다.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
