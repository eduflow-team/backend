"""학생 대시보드 관련 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DashboardAccessForbiddenError, InvalidTokenError
from app.models.assignment import Assignment
from app.models.student_status import StudentAssignmentStatus
from app.repositories.assignment import AssignmentRepository
from app.repositories.attendance import AttendanceRepository
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.user import UserRepository
from app.schemas.dashboard import StageSummaryItem, StudentDashboardSummaryResponse

_TOTAL_STAGE_COUNT = 4
_ATTENDED_STATUS = "PRESENT"
_KNOWN_PROGRESS_STATUSES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED"}


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.user_repository = UserRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.student_status_repository = StudentAssignmentStatusRepository(session)
        self.attendance_repository = AttendanceRepository(session)

    async def get_student_summary(self, user_id: int) -> StudentDashboardSummaryResponse:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            # 토큰 발급 이후 탈퇴(soft delete)된 사용자 등 → 인증 실패로 취급한다.
            raise InvalidTokenError()

        if user.role != "STUDENT":
            raise DashboardAccessForbiddenError()

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

        latest_by_stage: dict[int, Assignment] = {}
        for assignment in assignments:
            if assignment.stage is None or assignment.stage in latest_by_stage:
                continue
            latest_by_stage[assignment.stage] = assignment
        return latest_by_stage

    def _build_stage_summary(
        self,
        stage: int,
        assignment: Assignment | None,
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
    ) -> StageSummaryItem:
        if assignment is None:
            return StageSummaryItem(
                stage=stage, status="NOT_STARTED", score=None, remaining_attempts=None
            )

        status_row = status_by_assignment_id.get(assignment.assignment_id)
        if status_row is None:
            return StageSummaryItem(
                stage=stage, status="NOT_STARTED", score=None, remaining_attempts=None
            )

        progress_status = (status_row.progress_status or "NOT_STARTED").upper()
        if progress_status not in _KNOWN_PROGRESS_STATUSES:
            progress_status = "NOT_STARTED"

        return StageSummaryItem(
            stage=stage,
            status=progress_status,
            score=status_row.best_score,
            remaining_attempts=status_row.remaining_attempts,
        )

    async def _get_attendance_rate(self, user_id: int) -> float:
        records = await self.attendance_repository.list_by_user(user_id)
        if not records:
            return 0.0

        attended_count = sum(
            1 for r in records if r.status is not None and r.status.upper() == _ATTENDED_STATUS
        )
        return round(attended_count / len(records) * 100, 1)
