"""학생 대시보드 API의 Pydantic 응답 스키마."""

from datetime import UTC, datetime

from pydantic import BaseModel, field_serializer

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


class AssignmentSummaryItem(BaseModel):
    """GET /student/dashboard/assignments의 과제 항목."""

    assignment_id: int
    title: str | None
    max_attempts: int | None
    score: int | None
    stage: int | None
    due_date: datetime | None
    status: ProgressStatus

    @field_serializer("due_date")
    def serialize_due_date(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class StudentAssignmentListResponse(BaseModel):
    """GET /student/dashboard/assignments 성공 응답."""

    assignments: list[AssignmentSummaryItem]


class StageSubmissionRateItem(BaseModel):
    """GET /teacher/dashboard/summary의 단계별 제출률 통계 항목."""

    stage: int
    submitted_count: int
    submission_rate: float
    stage_average_score: float | None


class TeacherDashboardSummaryResponse(BaseModel):
    """GET /teacher/dashboard/summary 성공 응답.

    담당 학급이 없거나 학생이 한 명도 없는 경우, 계산 불가능한 값들은
    0/0.0으로 안전하게 반환한다 (학생 대시보드의 빈 상태 처리와 동일한 원칙).
    """

    total_students: int
    unsubmitted_count: int
    class_average_score: float
    stage_submission_rates: list[StageSubmissionRateItem]


class UnsubmittedStudentItem(BaseModel):
    """GET /teacher/dashboard/students/unsubmitted의 학생별 미제출 항목.

    `student_id`는 명세서 예시(`"std_001"`)와 달리 실제 스키마의 `user_id`(정수)를
    그대로 사용한다. 다른 API들도 동일하게 실제 PK 타입을 따르고 있어 일관성을 맞췄다.
    """

    student_id: int
    student_name: str
    missing_stage: list[int]


class TeacherUnsubmittedStudentsResponse(BaseModel):
    """GET /teacher/dashboard/students/unsubmitted 성공 응답."""

    unsubmitted_students: list[UnsubmittedStudentItem]


class TeacherAssignmentItem(BaseModel):
    """GET /teacher/dashboard/assignments의 과제 항목."""

    assignment_id: int
    stage: int | None
    title: str | None
    created_at: datetime | None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class TeacherAssignmentListResponse(BaseModel):
    """GET /teacher/dashboard/assignments 성공 응답."""

    assignments: list[TeacherAssignmentItem]


class ErrorDetail(BaseModel):
    """에러 응답 포맷 (FastAPI 표준). 401 / 403 / 500 공통."""

    detail: str
