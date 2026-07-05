"""학생 대시보드 API의 Pydantic 응답 스키마."""

from typing import Literal

from pydantic import BaseModel


class StageSummaryItem(BaseModel):
    """단계(stage)별 진행 상태 요약 항목."""

    stage: int
    status: Literal["NOT_STARTED", "IN_PROGRESS", "COMPLETED"]
    score: int | None
    remaining_attempts: int | None


class StudentDashboardSummaryResponse(BaseModel):
    """GET /student/dashboard/summary 성공 응답."""

    student_name: str | None
    total_score: int
    attendance_rate: float
    stage_summary: list[StageSummaryItem]


class ErrorDetail(BaseModel):
    """에러 응답 포맷 (FastAPI 표준). 401 / 403 / 500 공통."""

    detail: str
