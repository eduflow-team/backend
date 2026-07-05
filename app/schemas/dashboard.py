"""학생 대시보드 API의 Pydantic 응답 스키마."""

from pydantic import BaseModel

from app.models.enums import ProgressStatus


class StageSummaryItem(BaseModel):
    """단계(stage)별 진행 상태 요약 항목."""

    stage: int
    status: ProgressStatus
    score: int | None
    remaining_attempts: int | None


class StudentDashboardSummaryResponse(BaseModel):
    """GET /student/dashboard/summary 성공 응답.

    `name`은 가입(일반/소셜 모두) 시 필수값이라 정상적으로 인증된 유저라면
    항상 존재한다. (탈퇴 시 마스킹되어 null이 되지만, 탈퇴한 유저는
    `deleted_at` 필터에 걸려 애초에 이 API를 호출할 수 없다.)
    """

    student_name: str
    total_score: int
    attendance_rate: float
    stage_summary: list[StageSummaryItem]


class ErrorDetail(BaseModel):
    """에러 응답 포맷 (FastAPI 표준). 401 / 403 / 500 공통."""

    detail: str
