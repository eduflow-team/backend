"""출석(Attendance) 관련 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AttendanceAccessForbiddenError, InvalidTokenError
from app.models.attendance import AttendanceRecord
from app.models.enums import AttendanceStatus
from app.models.user import User
from app.repositories.attendance import AttendanceRepository
from app.repositories.user import UserRepository
from app.schemas.attendance import AttendanceRecordItem, StudentAttendanceResponse
from app.services.attendance_stats import compute_attendance_summary, normalize_attendance_status


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.user_repository = UserRepository(session)
        self.attendance_repository = AttendanceRepository(session)

    async def get_student_attendance(self, user_id: int) -> StudentAttendanceResponse:
        await self._get_authorized_student(user_id)
        records = await self.attendance_repository.list_by_user(user_id)

        attendance_rate, present_count, late_count, absent_count = compute_attendance_summary(
            records
        )
        items = [self._build_record_item(record) for record in records]

        return StudentAttendanceResponse(
            attendance_rate=attendance_rate,
            present_count=present_count,
            late_count=late_count,
            absent_count=absent_count,
            attendance_records=items,
        )

    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "STUDENT":
            raise AttendanceAccessForbiddenError()

        return user

    def _build_record_item(self, record: AttendanceRecord) -> AttendanceRecordItem:
        status = normalize_attendance_status(record.status)
        if status is None:
            status = AttendanceStatus.PENDING.value

        return AttendanceRecordItem(
            week=record.week_number,
            date=record.attendance_date,
            status=AttendanceStatus(status),
            note=record.note or "",
        )
