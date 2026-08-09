"""Stage 4: 프롬프트 인젝션 보안 실습 비즈니스 로직.

핵심은 (1) Langflow를 통해 `ai_response` 생성, (2) 백엔드 Rule로 클리어 판정,
(3) 실패 누적 기반 힌트, (4) 보고서 제출 후 결정형 루브릭 채점이다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.langflow_client import LangflowClient
from app.core.config import settings
from app.core.exceptions import (
    AssignmentNotFoundError,
    InvalidStage4CreateError,
    InvalidTokenError,
    Stage4AccessForbiddenError,
    Stage4LangflowServiceUnavailableError,
    Stage4ReportAlreadySubmittedError,
    Stage4ReportNotAvailableError,
    Stage4SubmitLimitExceededError,
    Stage4SubmitReportFieldsMissingError,
)
from app.models.assignment import Assignment
from app.models.enums import ProgressStatus
from app.models.submission import Submission
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.class_ import ClassRepository
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.submission import SubmissionRepository
from app.repositories.user import UserRepository
from app.services.grading.stage4_grader import Stage4Grader, Stage4ReportInput
from app.schemas.stage4 import (
    Difficulty,
    Stage4AssignmentDetailResponse,
    Stage4ChatResponse,
    Stage4CreateRequest,
    Stage4CreateResponse,
    Stage4Report,
    Stage4SubmitRequest,
    Stage4SubmitResponse,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Stage4AssignmentPayload:
    mission: str
    guideline: str
    secret_key: str
    difficulty: Difficulty


class Stage4Service:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.status_repository = StudentAssignmentStatusRepository(session)
        self.submission_repository = SubmissionRepository(session)
        self.langflow_client = LangflowClient()
        self.grader = Stage4Grader()

        self._ai_prompts_root = (
            Path(__file__).resolve().parents[3] / "ai" / "prompts" / "stage4"
        )

    # ------------------------------------------------------------------
    # Teacher: create
    # ------------------------------------------------------------------
    async def create_step4_assignment(
        self, *, user_id: int, payload: Stage4CreateRequest
    ) -> Stage4CreateResponse:
        teacher = await self._get_authorized_teacher(user_id)

        allowed_class_ids = await self._get_teacher_class_ids(teacher)
        if payload.class_id not in allowed_class_ids:
            raise Stage4AccessForbiddenError()

        assignment = Assignment(
            teacher_id=teacher.user_id,
            class_id=payload.class_id,
            title="4단계: 프롬프트 인젝션 보안 실습",
            stage=4,
            subject="ai",
            description=self._encode_detail(payload),
            max_attempts=payload.max_attempts,
        )
        assignment = await self.assignment_repository.create(assignment)

        await self.session.commit()

        return Stage4CreateResponse(
            assignment_id=assignment.assignment_id,
            title=assignment.title or "",
            mission=payload.mission,
            difficulty=payload.difficulty,
            max_attempts=payload.max_attempts,
        )

    # ------------------------------------------------------------------
    # Student: detail
    # ------------------------------------------------------------------
    async def get_step4_assignment(
        self, *, user_id: int, assignment_id: int
    ) -> Stage4AssignmentDetailResponse:
        student = await self._get_authorized_student(user_id)
        assignment = await self._get_stage4_assignment_for_student(
            student, assignment_id
        )
        detail = self._decode_detail(assignment)

        max_attempts = assignment.max_attempts or 10
        status = await self.status_repository.get_or_create(
            student.user_id,
            assignment_id,
            remaining_attempts=max_attempts,
        )

        # chat attempts = stage4 submissions where is_final=false
        attempts = await self._list_stage4_chat_attempts(
            student.user_id, assignment_id
        )
        used_attempts = len(attempts)
        remaining = max(0, max_attempts - used_attempts)

        is_cleared = any(a["attack_success"] for a in attempts)

        existing_final = await self.submission_repository.get_final_by_user_and_assignment(
            student.user_id, assignment_id
        )
        can_submit_report = is_cleared and existing_final is None

        attack_logs = [
            {
                "attempt_no": a["attempt_no"],
                "attack_prompt": a["attack_prompt"],
                "ai_response": a["ai_response"],
                "attack_success": a["attack_success"],
                "created_at": a["created_at"],
            }
            for a in sorted(attempts, key=lambda x: x["attempt_no"])
        ]

        return Stage4AssignmentDetailResponse(
            assignment_id=assignment.assignment_id,
            title=assignment.title or "",
            mission=detail.mission,
            guideline=detail.guideline,
            difficulty=detail.difficulty,
            status=status.progress_status or ProgressStatus.IN_PROGRESS.value,
            is_cleared=is_cleared,
            can_submit_report=can_submit_report,
            attempts={
                "max_attempts": max_attempts,
                "used_attempts": used_attempts,
                "remaining_attempts": remaining,
            },
            attack_logs=attack_logs,
        )

    # ------------------------------------------------------------------
    # Student: chat
    # ------------------------------------------------------------------
    async def chat_step4(
        self, *, user_id: int, assignment_id: int, attack_prompt: str
    ) -> Stage4ChatResponse:
        student = await self._get_authorized_student(user_id)
        assignment = await self._get_stage4_assignment_for_student(
            student, assignment_id
        )
        detail = self._decode_detail(assignment)

        if not attack_prompt.strip():
            raise InvalidStage4CreateError()

        max_attempts = assignment.max_attempts or 10
        status = await self.status_repository.get_or_create(
            student.user_id, assignment_id, remaining_attempts=max_attempts
        )

        existing_final = await self.submission_repository.get_final_by_user_and_assignment(
            student.user_id, assignment_id
        )
        if existing_final is not None:
            raise Stage4ReportAlreadySubmittedError()

        attempts = await self._list_stage4_chat_attempts(
            student.user_id, assignment_id
        )
        used_attempts = len(attempts)
        if used_attempts >= max_attempts:
            raise Stage4SubmitLimitExceededError()

        is_cleared = any(a["attack_success"] for a in attempts)
        failed_count = sum(1 for a in attempts if not a["attack_success"])

        hint_obj = self.grader.hint_for(
            difficulty=detail.difficulty,
            failed_count=failed_count,
            is_cleared=is_cleared,
        )
        hint_level = hint_obj.hint_level
        hint = hint_obj.hint

        if status.progress_status == ProgressStatus.NOT_STARTED.value:
            await self.status_repository.update_progress(
                status, progress_status=ProgressStatus.IN_PROGRESS.value
            )
            await self.session.commit()

        difficulty_prompt = self._read_defense_prompt(detail.difficulty)

        # system prompt에 mission+guideline을 함께 넣어 맥락을 강화한다.
        mission_context = f"{detail.mission}\n\n가이드라인: {detail.guideline}".strip()

        ai_response = await self.langflow_client.run_stage4_chat(
            attack_prompt=attack_prompt,
            mission=mission_context,
            secret_key=detail.secret_key,
            difficulty_prompt=difficulty_prompt,
            history="없음",
            hint=(hint or ""),
            difficulty=detail.difficulty,
        )

        attack_success = self.grader.is_attack_success(
            detail.secret_key,
            ai_response,
            difficulty=detail.difficulty,
            attack_prompt=attack_prompt,
        )
        is_cleared_after = is_cleared or attack_success

        attempt_no = used_attempts + 1
        submission = Submission(
            user_id=student.user_id,
            assignment_id=assignment_id,
            stage=4,
            submitted_answer=attack_prompt,
            final_parameters={
                "attempt_no": attempt_no,
                "ai_response": ai_response,
                "attack_success": attack_success,
                "hint_level": hint_level,
                "hint": hint,
            },
            current_score=None,
            is_final=False,
        )
        submission = await self.submission_repository.create(submission)

        # remaining update
        remaining = max(0, max_attempts - attempt_no)
        await self.status_repository.update_progress(
            status,
            remaining_attempts=remaining,
            progress_status=(
                ProgressStatus.COMPLETED.value
                if is_cleared_after
                else ProgressStatus.IN_PROGRESS.value
            ),
        )
        await self.session.commit()

        return Stage4ChatResponse(
            ai_response=ai_response,
            attack_success=attack_success,
            is_cleared=is_cleared_after,
            hint_level=hint_level,
            hint=hint if hint_level > 0 else None,
            attempts={
                "max_attempts": max_attempts,
                "used_attempts": attempt_no,
                "remaining_attempts": remaining,
            },
        )

    # ------------------------------------------------------------------
    # Student: submit report
    # ------------------------------------------------------------------
    async def submit_step4_report(
        self,
        *,
        user_id: int,
        assignment_id: int,
        payload: Stage4SubmitRequest,
    ) -> Stage4SubmitResponse:
        student = await self._get_authorized_student(user_id)
        assignment = await self._get_stage4_assignment_for_student(
            student, assignment_id
        )
        detail = self._decode_detail(assignment)

        max_attempts = assignment.max_attempts or 10

        attempts = await self._list_stage4_chat_attempts(
            student.user_id, assignment_id
        )
        is_cleared = any(a["attack_success"] for a in attempts)
        if not is_cleared:
            raise Stage4ReportNotAvailableError()

        existing_final = await self.submission_repository.get_final_by_user_and_assignment(
            student.user_id, assignment_id
        )
        if existing_final is not None:
            raise Stage4ReportAlreadySubmittedError()

        # first clear attempt_no
        first_clear = min(
            (a for a in attempts if a["attack_success"]),
            key=lambda x: x["attempt_no"],
        )
        attempts_used_at_clear = first_clear["attempt_no"]

        report: Stage4Report = payload.report
        evaluation = self.grader.evaluate_report(
            report=Stage4ReportInput(**report.model_dump()),
            attempts_used_at_clear=attempts_used_at_clear,
            max_attempts=max_attempts,
            difficulty=detail.difficulty,
        )

        status = await self.status_repository.get_or_create(
            student.user_id, assignment_id, remaining_attempts=max_attempts
        )

        # remaining attempts at submission time
        used_attempts = len(attempts)
        remaining = max(0, max_attempts - used_attempts)

        submission = Submission(
            user_id=student.user_id,
            assignment_id=assignment_id,
            stage=4,
            submitted_answer=json.dumps(report.model_dump(), ensure_ascii=False),
            final_parameters={
                "report": report.model_dump(),
                "evaluation_report": {
                    "clear_score": evaluation.clear_score,
                    "efficiency_score": evaluation.efficiency_score,
                    "analysis_score": evaluation.analysis_score,
                    "feedback": evaluation.feedback,
                    "analysis_breakdown": evaluation.analysis_breakdown,
                },
            },
            current_score=evaluation.current_score,
            is_final=True,
        )
        await self.submission_repository.create(submission)

        await self.status_repository.update_progress(
            status,
            progress_status=ProgressStatus.COMPLETED.value,
            best_score=evaluation.current_score,
            remaining_attempts=remaining,
        )
        await self.session.commit()

        return Stage4SubmitResponse(
            current_score=evaluation.current_score,
            is_passed=evaluation.is_passed,
            evaluation_report={
                "clear_score": evaluation.clear_score,
                "efficiency_score": evaluation.efficiency_score,
                "analysis_score": evaluation.analysis_score,
                "feedback": evaluation.feedback,
            },
            attempts={
                "max_attempts": max_attempts,
                "used_attempts": used_attempts,
                "remaining_attempts": remaining,
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "STUDENT":
            raise Stage4AccessForbiddenError()
        return user

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "TEACHER":
            raise Stage4AccessForbiddenError()
        return user

    async def _get_teacher_class_ids(self, teacher: User) -> set[int]:
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = {c.class_id for c in classes}
        if teacher.class_id is not None:
            class_ids.add(teacher.class_id)
        return class_ids

    async def _get_stage4_assignment_for_student(
        self, student: User, assignment_id: int
    ) -> Assignment:
        assignment = await self.assignment_repository.get_by_id(assignment_id)
        if assignment is None or assignment.stage != 4:
            raise AssignmentNotFoundError()
        if student.class_id is None or assignment.class_id != student.class_id:
            raise Stage4AccessForbiddenError()
        return assignment

    def _encode_detail(self, payload: Stage4CreateRequest) -> str:
        data = {
            "mission": payload.mission,
            "guideline": payload.guideline,
            "secret_key": payload.secret_key,
            "difficulty": payload.difficulty,
        }
        return json.dumps(data, ensure_ascii=False)

    def _decode_detail(self, assignment: Assignment) -> _Stage4AssignmentPayload:
        raw = assignment.description or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        return _Stage4AssignmentPayload(
            mission=(data.get("mission") or "").strip(),
            guideline=(data.get("guideline") or "").strip(),
            secret_key=(data.get("secret_key") or "").strip(),
            difficulty=(data.get("difficulty") or "NORMAL"),
        )

    async def _list_stage4_chat_attempts(
        self, user_id: int, assignment_id: int
    ) -> list[dict]:
        stmt = (
            select(Submission)
            .where(
                Submission.user_id == user_id,
                Submission.assignment_id == assignment_id,
                Submission.stage == 4,
                Submission.is_final.is_(False),
            )
            .order_by(Submission.created_at.asc())
        )
        result = await self.session.execute(stmt)
        rows: list[Submission] = list(result.scalars().all())

        parsed: list[dict] = []
        for r in rows:
            params = r.final_parameters or {}
            parsed.append(
                {
                    "attempt_no": params.get("attempt_no") or 0,
                    "attack_prompt": r.submitted_answer or "",
                    "ai_response": params.get("ai_response") or "",
                    "attack_success": bool(params.get("attack_success")),
                    "hint_level": params.get("hint_level") or 0,
                    "hint": params.get("hint"),
                    "created_at": r.created_at,
                }
            )
        return parsed

    def _read_defense_prompt(self, difficulty: str) -> str:
        difficulty = (difficulty or "").upper()
        filename = {
            "EASY": "defense-easy.md",
            "NORMAL": "defense-normal.md",
            "HARD": "defense-hard.md",
        }.get(difficulty, "defense-normal.md")

        path = self._ai_prompts_root / filename
        if not path.exists():
            logger.error("stage4 defense prompt missing: %s", path)
            raise InvalidStage4CreateError()

        raw = path.read_text(encoding="utf-8")

        # defense-*.md는 Text 섹션 1개를 코드블록으로 둔다.
        m = re.search(r"## Text[\s\S]*?```\n([\s\S]*?)\n```", raw)
        if not m:
            # fallback: 첫 코드블록만
            m2 = re.search(r"```\n([\s\S]*?)\n```", raw)
            if not m2:
                raise InvalidStage4CreateError()
            return m2.group(1).rstrip()
        return m.group(1).rstrip()

