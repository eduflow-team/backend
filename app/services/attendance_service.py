"""출석(Attendance) 관련 비즈니스 로직."""

from collections import defaultdict
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AttendanceAccessForbiddenError,
    AttendanceUpdateForbiddenError,
    InvalidTokenError,
)
from app.models.attendance import AttendanceRecord
from app.models.enums import AttendanceStatus
from app.models.user import User
from app.repositories.attendance import AttendanceRepository
from app.repositories.class_ import ClassRepository
from app.repositories.user import UserRepository
from app.schemas.attendance import (
    AttendanceRecordItem,
    StudentAttendanceResponse,
    TeacherAttendanceDateRecord,
    TeacherAttendanceResponse,
    TeacherAttendanceStudentItem,
    TeacherAttendanceUpdateRequest,
)
from app.services.attendance_stats import compute_attendance_summary, normalize_attendance_status


class AttendanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
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

    async def get_teacher_attendance(
        self,
        user_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> TeacherAttendanceResponse:
        teacher = await self._get_authorized_teacher(user_id)
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = [c.class_id for c in classes]

        students = await self.user_repository.list_by_class_ids(class_ids, role="STUDENT")
        if not students:
            return TeacherAttendanceResponse(attendance_dates=[], students=[])

        records = await self.attendance_repository.list_by_class_ids(class_ids)
        attendance_dates = self._build_attendance_dates(records, from_date=from_date, to_date=to_date)
        records_by_user_date = self._group_records_by_user_date(records)

        student_items = [
            self._build_teacher_student_item(
                student,
                records,
                attendance_dates,
                records_by_user_date.get(student.user_id, {}),
            )
            for student in students
        ]

        return TeacherAttendanceResponse(
            attendance_dates=attendance_dates,
            students=student_items,
        )

    async def update_teacher_attendance(
        self,
        user_id: int,
        payload: TeacherAttendanceUpdateRequest,
    ) -> dict:
        teacher = await self._get_authorized_teacher_for_update(user_id)
        allowed_student_ids = await self._get_teacher_student_ids(teacher.user_id)

        for item in payload.records:
            if item.student_id not in allowed_student_ids:
                raise AttendanceUpdateForbiddenError()

            await self.attendance_repository.upsert_by_user_and_date(
                user_id=item.student_id,
                attendance_date=payload.date,
                status=self._status_to_db(item.status),
                note=item.note,
            )

        await self.session.commit()
        return {}

    async def _get_teacher_student_ids(self, teacher_id: int) -> set[int]:
        classes = await self.class_repository.list_by_teacher(teacher_id)
        class_ids = [c.class_id for c in classes]
        students = await self.user_repository.list_by_class_ids(class_ids, role="STUDENT")
        return {student.user_id for student in students}

    async def _get_authorized_teacher_for_update(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "TEACHER":
            raise AttendanceUpdateForbiddenError()

        return user

    def _status_to_db(self, status: AttendanceStatus) -> str | None:
        if status == AttendanceStatus.PENDING:
            return None
        return status.value

    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "STUDENT":
            raise AttendanceAccessForbiddenError()

        return user

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "TEACHER":
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

    def _build_attendance_dates(
        self,
        records: list[AttendanceRecord],
        *,
        from_date: date | None,
        to_date: date | None,
    ) -> list[date]:
        dates = {
            record.attendance_date
            for record in records
            if record.attendance_date is not None
        }
        dates.add(date.today())

        attendance_dates = sorted(dates)
        if from_date is not None:
            attendance_dates = [d for d in attendance_dates if d >= from_date]
        if to_date is not None:
            attendance_dates = [d for d in attendance_dates if d <= to_date]
        return attendance_dates

    def _group_records_by_user_date(
        self,
        records: list[AttendanceRecord],
    ) -> dict[int, dict[date, AttendanceRecord]]:
        grouped: dict[int, dict[date, AttendanceRecord]] = defaultdict(dict)
        for record in records:
            if record.attendance_date is None:
                continue
            grouped[record.user_id][record.attendance_date] = record
        return grouped

    def _build_teacher_student_item(
        self,
        student: User,
        all_records: list[AttendanceRecord],
        attendance_dates: list[date],
        records_by_date: dict[date, AttendanceRecord],
    ) -> TeacherAttendanceStudentItem:
        student_records = [record for record in all_records if record.user_id == student.user_id]
        attendance_rate, _, _, _ = compute_attendance_summary(student_records)
        today = date.today()

        date_records = [
            self._build_teacher_date_record(attendance_date, records_by_date, today)
            for attendance_date in attendance_dates
        ]

        return TeacherAttendanceStudentItem(
            student_id=student.user_id,
            student_name=student.name or "",
            attendance_rate=attendance_rate,
            records=date_records,
        )

    def _build_teacher_date_record(
        self,
        attendance_date: date,
        records_by_date: dict[date, AttendanceRecord],
        today: date,
    ) -> TeacherAttendanceDateRecord:
        record = records_by_date.get(attendance_date)
        if record is not None:
            status = normalize_attendance_status(record.status)
            if status is None:
                status = AttendanceStatus.PENDING.value
            return TeacherAttendanceDateRecord(
                date=attendance_date,
                status=AttendanceStatus(status),
                note=record.note or "",
            )

        if attendance_date == today:
            return TeacherAttendanceDateRecord(
                date=attendance_date,
                status=AttendanceStatus.PENDING,
                note="",
            )

        return TeacherAttendanceDateRecord(
            date=attendance_date,
            status=AttendanceStatus.ABSENT,
            note="",
        )
