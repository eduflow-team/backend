"""학생/교사 대시보드 관련 비즈니스 로직."""

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DashboardAccessForbiddenError, InvalidTokenError
from app.models.assignment import Assignment
from app.models.enums import AttendanceStatus, ProgressStatus
from app.models.student_status import StudentAssignmentStatus
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.attendance import AttendanceRepository
from app.repositories.class_ import ClassRepository
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.user import UserRepository
from app.schemas.dashboard import (
    AssignmentSummaryItem,
    StageSubmissionRateItem,
    StageSummaryItem,
    StudentAssignmentListResponse,
    StudentDashboardSummaryResponse,
    TeacherDashboardSummaryResponse,
    TeacherUnsubmittedStudentsResponse,
    UnsubmittedStudentItem,
)

_TOTAL_STAGE_COUNT = 4
_KNOWN_PROGRESS_STATUSES = {s.value for s in ProgressStatus}


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.student_status_repository = StudentAssignmentStatusRepository(session)
        self.attendance_repository = AttendanceRepository(session)

    async def get_student_summary(self, user_id: int) -> StudentDashboardSummaryResponse:
        user = await self._get_authorized_student(user_id)

        statuses = await self.student_status_repository.list_by_user(user_id)
        status_by_assignment_id = {s.assignment_id: s for s in statuses}

        latest_assignment_by_stage = await self._get_latest_assignment_by_stage(user.class_id)

        stage_summary = [
            self._build_stage_summary(
                stage,
                latest_assignment_by_stage.get(stage),
                status_by_assignment_id,
            )
            for stage in range(1, _TOTAL_STAGE_COUNT + 1)
        ]

        total_score = sum(
            s.total_literacy_score for s in statuses if s.total_literacy_score is not None
        )
        attendance_rate = await self._get_attendance_rate(user_id)

        return StudentDashboardSummaryResponse(
            student_name=user.name,
            total_score=total_score,
            attendance_rate=attendance_rate,
            stage_summary=stage_summary,
        )

    async def get_student_assignments(self, user_id: int) -> StudentAssignmentListResponse:
        user = await self._get_authorized_student(user_id)

        assignments: list[Assignment] = []
        if user.class_id is not None:
            assignments = await self.assignment_repository.list_by_class(user.class_id)

        statuses = await self.student_status_repository.list_by_user(user_id)
        status_by_assignment_id = {s.assignment_id: s for s in statuses}

        items = [
            self._build_assignment_item(
                assignment, status_by_assignment_id.get(assignment.assignment_id)
            )
            for assignment in assignments
        ]
        return StudentAssignmentListResponse(assignments=items)

    async def get_teacher_summary(self, user_id: int) -> TeacherDashboardSummaryResponse:
        teacher = await self._get_authorized_teacher(user_id)
        (
            students,
            statuses_by_student,
            latest_assignment_by_stage,
        ) = await self._load_teacher_dashboard_context(teacher.user_id)

        total_students = len(students)
        total_score_by_student = {
            student.user_id: self._get_total_score(statuses_by_student.get(student.user_id, {}))
            for student in students
        }
        class_average_score = (
            round(sum(total_score_by_student.values()) / total_students, 1)
            if total_students
            else 0.0
        )

        unsubmitted_count = sum(
            1
            for student in students
            if self._has_missing_stage(
                statuses_by_student.get(student.user_id, {}), latest_assignment_by_stage
            )
        )

        stage_submission_rates = [
            self._build_stage_submission_rate(stage, assignment, students, statuses_by_student)
            for stage, assignment in sorted(latest_assignment_by_stage.items())
        ]

        return TeacherDashboardSummaryResponse(
            total_students=total_students,
            unsubmitted_count=unsubmitted_count,
            class_average_score=class_average_score,
            stage_submission_rates=stage_submission_rates,
        )

    async def get_unsubmitted_students(self, user_id: int) -> TeacherUnsubmittedStudentsResponse:
        teacher = await self._get_authorized_teacher(user_id)
        (
            students,
            statuses_by_student,
            latest_assignment_by_stage,
        ) = await self._load_teacher_dashboard_context(teacher.user_id)

        unsubmitted_students = [
            UnsubmittedStudentItem(
                student_id=student.user_id,
                student_name=student.name,
                missing_stage=missing_stages,
            )
            for student in students
            if (
                missing_stages := self._get_missing_stages(
                    statuses_by_student.get(student.user_id, {}), latest_assignment_by_stage
                )
            )
        ]

        return TeacherUnsubmittedStudentsResponse(unsubmitted_students=unsubmitted_students)

    async def _load_teacher_dashboard_context(
        self, teacher_id: int
    ) -> tuple[list[User], dict[int, dict[int, StudentAssignmentStatus]], dict[int, Assignment]]:
        """교사 대시보드 API들이 공통으로 필요로 하는 학급/학생/과제/진행상태를 모아 반환한다."""

        classes = await self.class_repository.list_by_teacher(teacher_id)
        class_ids = [c.class_id for c in classes]

        students = await self.user_repository.list_by_class_ids(class_ids, role="STUDENT")
        assignments = await self.assignment_repository.list_by_class_ids(class_ids)
        assignment_ids = [a.assignment_id for a in assignments]

        statuses = await self.student_status_repository.list_by_assignment_ids(assignment_ids)
        statuses_by_student = self._group_statuses_by_student(statuses)
        latest_assignment_by_stage = self._group_latest_by_stage(assignments)

        return students, statuses_by_student, latest_assignment_by_stage

    async def _get_authorized_student(self, user_id: int) -> User:
        return await self._get_authorized_user(user_id, "STUDENT")

    async def _get_authorized_teacher(self, user_id: int) -> User:
        return await self._get_authorized_user(user_id, "TEACHER")

    async def _get_authorized_user(self, user_id: int, required_role: str) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            # 토큰 발급 이후 탈퇴(soft delete)된 사용자 등 → 인증 실패로 취급한다.
            raise InvalidTokenError()

        if user.role != required_role:
            raise DashboardAccessForbiddenError()

        return user

    async def _get_latest_assignment_by_stage(
        self, class_id: int | None
    ) -> dict[int, Assignment]:
        """학급의 단계별 '현재' 과제를 반환한다.

        한 학급에 같은 단계의 과제가 여러 번 생성될 수 있다고 가정하고,
        가장 최근에 생성된 과제를 해당 단계의 대표 과제로 취급한다.
        """

        if class_id is None:
            return {}

        assignments = await self.assignment_repository.list_by_class(class_id)
        return self._group_latest_by_stage(assignments)

    def _group_latest_by_stage(self, assignments: list[Assignment]) -> dict[int, Assignment]:
        latest_by_stage: dict[int, Assignment] = {}
        for assignment in assignments:
            if assignment.stage is None or assignment.stage in latest_by_stage:
                continue
            latest_by_stage[assignment.stage] = assignment
        return latest_by_stage

    def _group_statuses_by_student(
        self, statuses: list[StudentAssignmentStatus]
    ) -> dict[int, dict[int, StudentAssignmentStatus]]:
        by_student: dict[int, dict[int, StudentAssignmentStatus]] = defaultdict(dict)
        for status_row in statuses:
            by_student[status_row.user_id][status_row.assignment_id] = status_row
        return by_student

    def _get_total_score(self, status_by_assignment_id: dict[int, StudentAssignmentStatus]) -> int:
        return sum(
            s.total_literacy_score
            for s in status_by_assignment_id.values()
            if s.total_literacy_score is not None
        )

    def _has_missing_stage(
        self,
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
        latest_assignment_by_stage: dict[int, Assignment],
    ) -> bool:
        return bool(
            self._get_missing_stages(status_by_assignment_id, latest_assignment_by_stage)
        )

    def _get_missing_stages(
        self,
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
        latest_assignment_by_stage: dict[int, Assignment],
    ) -> list[int]:
        """학생이 아직 `COMPLETED`하지 못한 단계 번호 목록을 오름차순으로 반환한다."""

        missing_stages = []
        for stage, assignment in sorted(latest_assignment_by_stage.items()):
            status_row = status_by_assignment_id.get(assignment.assignment_id)
            progress_status, _ = self._resolve_progress(status_row)
            if progress_status != ProgressStatus.COMPLETED.value:
                missing_stages.append(stage)
        return missing_stages

    def _build_stage_submission_rate(
        self,
        stage: int,
        assignment: Assignment,
        students: list[User],
        statuses_by_student: dict[int, dict[int, StudentAssignmentStatus]],
    ) -> StageSubmissionRateItem:
        completed_scores: list[int] = []
        for student in students:
            status_row = statuses_by_student.get(student.user_id, {}).get(
                assignment.assignment_id
            )
            progress_status, _ = self._resolve_progress(status_row)
            if (
                progress_status == ProgressStatus.COMPLETED.value
                and status_row is not None
                and status_row.total_literacy_score is not None
            ):
                completed_scores.append(status_row.total_literacy_score)

        submitted_count = len(completed_scores)
        total_students = len(students)
        submission_rate = (
            round(submitted_count / total_students * 100, 1) if total_students else 0.0
        )
        stage_average_score = (
            round(sum(completed_scores) / submitted_count, 1) if submitted_count else None
        )

        return StageSubmissionRateItem(
            stage=stage,
            submitted_count=submitted_count,
            submission_rate=submission_rate,
            stage_average_score=stage_average_score,
        )

    def _build_stage_summary(
        self,
        stage: int,
        assignment: Assignment | None,
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
    ) -> StageSummaryItem:
        status_row = (
            status_by_assignment_id.get(assignment.assignment_id) if assignment else None
        )
        progress_status, score = self._resolve_progress(status_row)

        return StageSummaryItem(
            stage=stage,
            status=progress_status,
            score=score,
            remaining_attempts=status_row.remaining_attempts if status_row else None,
        )

    def _build_assignment_item(
        self,
        assignment: Assignment,
        status_row: StudentAssignmentStatus | None,
    ) -> AssignmentSummaryItem:
        progress_status, score = self._resolve_progress(status_row)

        return AssignmentSummaryItem(
            assignment_id=assignment.assignment_id,
            title=assignment.title,
            max_attempts=assignment.max_attempts,
            score=score,
            stage=assignment.stage,
            due_date=assignment.due_at,
            status=progress_status,
        )

    def _resolve_progress(
        self, status_row: StudentAssignmentStatus | None
    ) -> tuple[str, int | None]:
        """진행 상태 기록을 안전하게 정규화해 (status, score)로 반환한다.

        기록이 없거나 알 수 없는 값이면 `NOT_STARTED`/`None`으로 취급한다.
        """

        if status_row is None:
            return ProgressStatus.NOT_STARTED.value, None

        progress_status = (status_row.progress_status or ProgressStatus.NOT_STARTED.value).upper()
        if progress_status not in _KNOWN_PROGRESS_STATUSES:
            progress_status = ProgressStatus.NOT_STARTED.value

        return progress_status, status_row.best_score

    async def _get_attendance_rate(self, user_id: int) -> float:
        records = await self.attendance_repository.list_by_user(user_id)
        if not records:
            return 0.0

        attended_count = sum(
            1
            for r in records
            if r.status is not None and r.status.upper() == AttendanceStatus.PRESENT.value
        )
        return round(attended_count / len(records) * 100, 1)
