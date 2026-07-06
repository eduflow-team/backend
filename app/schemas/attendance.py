"""출석(Attendance) API의 Pydantic 응답 스키마."""

from datetime import date

from pydantic import BaseModel, field_serializer

from app.models.enums import AttendanceStatus


class AttendanceRecordItem(BaseModel):
    """GET /student/attendance의 주차별 출석 기록 항목."""

    week: int | None
    date: date | None
    status: AttendanceStatus
    note: str

    @field_serializer("date")
    def serialize_date(self, value: date | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()


class StudentAttendanceResponse(BaseModel):
    """GET /student/attendance 성공 응답."""

    attendance_rate: float
    present_count: int
    late_count: int
    absent_count: int
    attendance_records: list[AttendanceRecordItem]


class TeacherAttendanceDateRecord(BaseModel):
    """GET /teacher/attendance의 학생별 날짜 출석 셀."""

    date: date
    status: AttendanceStatus
    note: str

    @field_serializer("date")
    def serialize_date(self, value: date) -> str:
        return value.isoformat()


class TeacherAttendanceStudentItem(BaseModel):
    """GET /teacher/attendance의 학생 행.

    `student_id`는 명세 예시(`"std_001"`)와 달리 실제 `users.user_id`(정수)를 사용한다.
    """

    student_id: int
    student_name: str
    attendance_rate: float
    records: list[TeacherAttendanceDateRecord]


class TeacherAttendanceResponse(BaseModel):
    """GET /teacher/attendance 성공 응답."""

    attendance_dates: list[date]
    students: list[TeacherAttendanceStudentItem]

    @field_serializer("attendance_dates")
    def serialize_attendance_dates(self, value: list[date]) -> list[str]:
        return [d.isoformat() for d in value]


class ErrorDetail(BaseModel):
    """에러 응답 포맷 (FastAPI 표준). 401 / 403 / 500 공통."""

    detail: str
