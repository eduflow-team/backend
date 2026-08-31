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
    Stage4DifficultyLockedError,
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
from app.services.grading.stage4_grader import (
    PASS_THRESHOLD,
    Stage4Grader,
    Stage4ReportInput,
)
from app.schemas.stage4 import (
    Difficulty,
    Stage4AssignmentDetailResponse,
    Stage4ChatResponse,
    Stage4CreateRequest,
    Stage4CreateResponse,
    Stage4DifficultyAssignment,
    Stage4DifficultyHints,
    Stage4DifficultyScoreItem,
    Stage4EvaluationReport,
    Stage4HintItem,
    Stage4LiteracyAxesScore,
    Stage4Report,
    Stage4SetScore,
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

    _DIFFICULTIES: list[Difficulty] = ["EASY", "NORMAL", "HARD"]

    # ------------------------------------------------------------------
    # Teacher: create (3개 난이도 동시 생성, 순차 해금)
    # ------------------------------------------------------------------
    async def create_step4_assignment(
        self, *, user_id: int, payload: Stage4CreateRequest
    ) -> Stage4CreateResponse:
        teacher = await self._get_authorized_teacher(user_id)

        allowed_class_ids = await self._get_teacher_class_ids(teacher)
        if payload.class_id not in allowed_class_ids:
            raise Stage4AccessForbiddenError()

        set_title = payload.title.strip() or "4단계: 프롬프트 인젝션 보안 실습"

        created: list[Assignment] = []
        for diff in self._DIFFICULTIES:
            assignment = Assignment(
                teacher_id=teacher.user_id,
                class_id=payload.class_id,
                title=set_title,
                stage=4,
                subject="ai",
                description=self._encode_detail_with_difficulty(payload, diff),
                max_attempts=payload.max_attempts,
            )
            assignment = await self.assignment_repository.create(assignment)
            created.append(assignment)

        # 첫 번째 assignment_id를 set_id로 사용
        set_id = created[0].assignment_id
        for a in created:
            a.set_id = set_id

        await self.session.commit()

        return Stage4CreateResponse(
            set_id=set_id,
            title=set_title,
            mission=payload.mission,
            max_attempts=payload.max_attempts,
            assignments=[
                Stage4DifficultyAssignment(
                    assignment_id=a.assignment_id,
                    difficulty=json.loads(a.description or "{}").get("difficulty", "NORMAL"),
                )
                for a in created
            ],
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
        failed_count = sum(1 for a in attempts if not a["attack_success"])
        hint_obj = self.grader.hint_for(
            difficulty=detail.difficulty,
            failed_count=failed_count,
            is_cleared=is_cleared,
        )

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

        unlocked = await self._is_difficulty_unlocked(student, assignment)

        return Stage4AssignmentDetailResponse(
            assignment_id=assignment.assignment_id,
            title=assignment.title or "",
            mission=detail.mission,
            guideline=detail.guideline,
            difficulty=detail.difficulty,
            unlocked=unlocked,
            status=status.progress_status or ProgressStatus.IN_PROGRESS.value,
            is_cleared=is_cleared,
            attempts={
                "max_attempts": max_attempts,
                "used_attempts": used_attempts,
                "remaining_attempts": remaining,
            },
            attack_logs=attack_logs,
            hint_level=hint_obj.hint_level,
            hint=hint_obj.hint if hint_obj.hint_level > 0 else None,
            hints=[
                Stage4HintItem.model_validate(item)
                for item in self.grader.hints_catalog(
                    difficulty=detail.difficulty,
                    hint_level=hint_obj.hint_level,
                )
            ],
            set=await self._build_set_score(student, assignment),
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

        if not await self._is_difficulty_unlocked(student, assignment):
            raise Stage4DifficultyLockedError()

        detail = self._decode_detail(assignment)

        if not attack_prompt.strip():
            raise InvalidStage4CreateError()

        max_attempts = assignment.max_attempts or 10
        status = await self.status_repository.get_or_create(
            student.user_id, assignment_id, remaining_attempts=max_attempts
        )

        set_id = assignment.set_id or assignment.assignment_id
        if await self._get_set_report_submission(student.user_id, set_id) is not None:
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

        set_id = assignment.set_id or assignment.assignment_id
        siblings = await self._list_set_siblings(assignment)

        if await self._get_set_report_submission(student.user_id, set_id) is not None:
            raise Stage4ReportAlreadySubmittedError()

        report: Stage4Report = payload.report
        evaluation, current_score = await self._evaluate_set_report(
            student, siblings, report
        )

        anchor_id = set_id
        anchor = next((s for s in siblings if s.assignment_id == anchor_id), assignment)
        max_attempts = anchor.max_attempts or 10

        submission = Submission(
            user_id=student.user_id,
            assignment_id=anchor_id,
            stage=4,
            submitted_answer=json.dumps(report.model_dump(), ensure_ascii=False),
            final_parameters={
                "scope": "set",
                "set_id": set_id,
                "report": report.model_dump(),
                "evaluation_report": {
                    "clear_score": evaluation.clear_score,
                    "efficiency_score": evaluation.efficiency_score,
                    "analysis_score": evaluation.analysis_score,
                    "feedback": evaluation.feedback,
                    "analysis_breakdown": evaluation.analysis_breakdown,
                    "literacy_axes": (
                        evaluation.literacy_axes.as_dict()
                        if evaluation.literacy_axes
                        else None
                    ),
                },
                "literacy_axes": (
                    evaluation.literacy_axes.as_dict()
                    if evaluation.literacy_axes
                    else None
                ),
            },
            current_score=current_score,
            is_final=True,
        )
        await self.submission_repository.create(submission)

        for sibling in siblings:
            sib_attempts = await self._list_stage4_chat_attempts(
                student.user_id, sibling.assignment_id
            )
            sib_max = sibling.max_attempts or 10
            sib_used = len(sib_attempts)
            sib_remaining = max(0, sib_max - sib_used)
            sib_status = await self.status_repository.get_or_create(
                student.user_id, sibling.assignment_id, remaining_attempts=sib_max
            )
            await self.status_repository.update_progress(
                sib_status,
                progress_status=ProgressStatus.COMPLETED.value,
                best_score=current_score,
                remaining_attempts=sib_remaining,
            )

        await self.session.commit()

        set_score = await self._build_set_score(student, assignment)

        return Stage4SubmitResponse(
            current_score=current_score,
            is_passed=current_score >= PASS_THRESHOLD,
            evaluation_report={
                "clear_score": evaluation.clear_score,
                "efficiency_score": evaluation.efficiency_score,
                "analysis_score": evaluation.analysis_score,
                "feedback": evaluation.feedback,
                "literacy_axes": (
                    evaluation.literacy_axes.as_dict()
                    if evaluation.literacy_axes
                    else None
                ),
            },
            attempts={
                "max_attempts": max_attempts,
                "used_attempts": len(
                    await self._list_stage4_chat_attempts(student.user_id, anchor_id)
                ),
                "remaining_attempts": max(
                    0,
                    max_attempts
                    - len(
                        await self._list_stage4_chat_attempts(
                            student.user_id, anchor_id
                        )
                    ),
                ),
            },
            set=set_score,
        )

    async def get_step4_set_score(
        self, *, user_id: int, assignment_id: int
    ) -> Stage4SetScore:
        student = await self._get_authorized_student(user_id)
        assignment = await self._get_stage4_assignment_for_student(
            student, assignment_id
        )
        return await self._build_set_score(student, assignment)

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

    _DIFF_ORDER: dict[str, int] = {"EASY": 0, "NORMAL": 1, "HARD": 2}

    async def _get_stage4_assignment_for_student(
        self, student: User, assignment_id: int
    ) -> Assignment:
        assignment = await self.assignment_repository.get_by_id(assignment_id)
        if assignment is None or assignment.stage != 4:
            raise AssignmentNotFoundError()
        if student.class_id is None or assignment.class_id != student.class_id:
            raise Stage4AccessForbiddenError()
        return assignment

    async def _is_difficulty_unlocked(
        self, student: User, assignment: Assignment
    ) -> bool:
        """EASY는 항상 해금. NORMAL은 EASY 클리어 후, HARD는 NORMAL 클리어 후."""
        detail = self._decode_detail(assignment)
        diff = detail.difficulty.upper()

        if diff == "EASY":
            return True

        if assignment.set_id is None:
            return True

        siblings = await self.assignment_repository.list_by_set_id(assignment.set_id)

        prev_diff = "EASY" if diff == "NORMAL" else "NORMAL"
        prev_assignment = next(
            (
                a
                for a in siblings
                if json.loads(a.description or "{}").get("difficulty", "").upper() == prev_diff
            ),
            None,
        )
        if prev_assignment is None:
            return True

        prev_attempts = await self._list_stage4_chat_attempts(
            student.user_id, prev_assignment.assignment_id
        )
        return any(a["attack_success"] for a in prev_attempts)

    async def _list_set_siblings(self, assignment: Assignment) -> list[Assignment]:
        if assignment.set_id is not None:
            return await self.assignment_repository.list_by_set_id(assignment.set_id)
        return [assignment]

    async def _get_set_report_submission(
        self, user_id: int, set_id: int
    ) -> Submission | None:
        return await self.submission_repository.get_final_by_user_and_assignment(
            user_id, set_id
        )

    async def _evaluate_set_report(
        self,
        student: User,
        siblings: list[Assignment],
        report: Stage4Report,
    ) -> tuple[object, int]:
        from app.services.grading.stage4_grader import (
            CLEAR_BY_DIFFICULTY,
            Stage4EvaluationReport as GraderEvaluationReport,
            score_clear,
            score_literacy_axes,
        )

        cleared_stats: list[tuple[str, int, int]] = []
        for sibling in siblings:
            attempts = await self._list_stage4_chat_attempts(
                student.user_id, sibling.assignment_id
            )
            successes = [a for a in attempts if a["attack_success"]]
            if not successes:
                continue
            first_clear = min(successes, key=lambda x: x["attempt_no"])
            detail = self._decode_detail(sibling)
            cleared_stats.append(
                (
                    (detail.difficulty or "NORMAL").upper(),
                    first_clear["attempt_no"],
                    sibling.max_attempts or 10,
                )
            )

        if not cleared_stats:
            raise Stage4ReportNotAvailableError()

        cleared_diffs = [diff for diff, _used, _mx in cleared_stats]
        clear_score = score_clear(cleared_diffs)
        hard_clear_points = CLEAR_BY_DIFFICULTY["HARD"] if "HARD" in cleared_diffs else 0
        efficiency_scores = [
            self.grader.score_efficiency(
                attempts_used=used,
                max_attempts=mx,
                difficulty=diff,
            )
            for diff, used, mx in cleared_stats
        ]
        efficiency_score = round(sum(efficiency_scores) / len(efficiency_scores))
        analysis, notes, breakdown = self.grader.score_analysis(
            Stage4ReportInput(**report.model_dump())
        )
        literacy_axes = score_literacy_axes(
            clear_score=clear_score,
            efficiency_score=efficiency_score,
            breakdown=breakdown,
            hard_clear_points=hard_clear_points,
        )

        if not notes:
            feedback = "클리어에 성공했고, 실패 원인과 방어 아이디어도 잘 정리했습니다."
        elif analysis >= 20:
            feedback = "클리어에 성공했습니다. " + " ".join(notes[:2])
        else:
            feedback = "클리어는 했지만 보고서가 부족합니다. " + " ".join(notes)

        evaluation = GraderEvaluationReport(
            clear_score=clear_score,
            efficiency_score=efficiency_score,
            analysis_score=analysis,
            feedback=feedback,
            analysis_breakdown=breakdown,
            literacy_axes=literacy_axes,
        )
        return evaluation, evaluation.current_score

    async def _build_set_score(
        self, student: User, assignment: Assignment
    ) -> Stage4SetScore:
        siblings = await self._list_set_siblings(assignment)
        set_id = assignment.set_id or assignment.assignment_id
        items: list[Stage4DifficultyScoreItem] = []
        difficulty_hints: list[Stage4DifficultyHints] = []
        cleared_count = 0

        for sibling in siblings:
            detail = self._decode_detail(sibling)
            difficulty = (detail.difficulty or "NORMAL").upper()
            attempts = await self._list_stage4_chat_attempts(
                student.user_id, sibling.assignment_id
            )
            is_cleared = any(a["attack_success"] for a in attempts)
            failed_count = sum(1 for a in attempts if not a["attack_success"])
            hint_obj = self.grader.hint_for(
                difficulty=difficulty,
                failed_count=failed_count,
                is_cleared=is_cleared,
            )
            difficulty_hints.append(
                Stage4DifficultyHints(
                    difficulty=difficulty,  # type: ignore[arg-type]
                    hint_level=hint_obj.hint_level,
                    hints=[
                        Stage4HintItem.model_validate(item)
                        for item in self.grader.hints_catalog(
                            difficulty=difficulty,
                            hint_level=hint_obj.hint_level,
                        )
                    ],
                )
            )
            if is_cleared:
                cleared_count += 1
            items.append(
                Stage4DifficultyScoreItem(
                    assignment_id=sibling.assignment_id,
                    difficulty=difficulty,  # type: ignore[arg-type]
                    unlocked=await self._is_difficulty_unlocked(student, sibling),
                    is_cleared=is_cleared,
                )
            )

        items.sort(key=lambda x: self._DIFF_ORDER.get(x.difficulty, 99))
        difficulty_hints.sort(key=lambda x: self._DIFF_ORDER.get(x.difficulty, 99))

        set_report = await self._get_set_report_submission(student.user_id, set_id)
        submitted_report, evaluation_report, current_score, is_passed = (
            self._parse_submitted_report(set_report)
        )
        report_submitted = set_report is not None
        can_submit_report = cleared_count > 0 and not report_submitted
        overall = current_score if current_score is not None else 0

        return Stage4SetScore(
            set_id=set_id,
            overall_score=overall,
            is_passed=is_passed if is_passed is not None else overall >= PASS_THRESHOLD,
            cleared_count=cleared_count,
            can_submit_report=can_submit_report,
            report_submitted=report_submitted,
            submitted_report=submitted_report,
            evaluation_report=evaluation_report,
            current_score=current_score,
            difficulties=items,
            difficulty_hints=difficulty_hints,
        )

    def _parse_submitted_report(
        self, final: Submission | None
    ) -> tuple[Stage4Report | None, Stage4EvaluationReport | None, int | None, bool | None]:
        if final is None:
            return None, None, None, None

        params = final.final_parameters or {}
        report_data = params.get("report")
        eval_data = params.get("evaluation_report")

        submitted_report: Stage4Report | None = None
        if isinstance(report_data, dict):
            try:
                submitted_report = Stage4Report.model_validate(report_data)
            except Exception:
                pass
        elif final.submitted_answer:
            try:
                submitted_report = Stage4Report.model_validate(json.loads(final.submitted_answer))
            except Exception:
                pass

        evaluation_report: Stage4EvaluationReport | None = None
        if isinstance(eval_data, dict):
            try:
                lit_raw = eval_data.get("literacy_axes") or params.get("literacy_axes")
                lit = None
                if isinstance(lit_raw, dict):
                    lit = Stage4LiteracyAxesScore(
                        ethics=int(lit_raw.get("ethics", 0)),
                        critical=int(lit_raw.get("critical", 0)),
                        collaboration=int(lit_raw.get("collaboration", 0)),
                    )
                evaluation_report = Stage4EvaluationReport(
                    clear_score=int(eval_data.get("clear_score", 0)),
                    efficiency_score=int(eval_data.get("efficiency_score", 0)),
                    analysis_score=int(eval_data.get("analysis_score", 0)),
                    feedback=str(eval_data.get("feedback") or ""),
                    literacy_axes=lit,
                )
            except Exception:
                pass

        current_score = final.current_score
        is_passed = (
            current_score >= PASS_THRESHOLD if current_score is not None else None
        )
        return submitted_report, evaluation_report, current_score, is_passed

    def _encode_detail(self, payload: Stage4CreateRequest) -> str:
        return self._encode_detail_with_difficulty(payload, "NORMAL")

    def _encode_detail_with_difficulty(
        self, payload: Stage4CreateRequest, difficulty: str
    ) -> str:
        data = {
            "mission": payload.mission,
            "guideline": payload.guideline,
            "secret_key": payload.secret_key,
            "difficulty": difficulty,
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

