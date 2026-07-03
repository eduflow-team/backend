from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord
from app.models.user import User
from app.repositories.base import BaseRepository


class AttendanceRepository(BaseRepository[AttendanceRecord]):
    model = AttendanceRecord

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_user(self, user_id: int) -> list[AttendanceRecord]:
        stmt = (
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == user_id)
            .order_by(AttendanceRecord.week_number, AttendanceRecord.attendance_date)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_class(self, class_id: int) -> list[AttendanceRecord]:
        stmt = (
            select(AttendanceRecord)
            .join(User, AttendanceRecord.user_id == User.user_id)
            .where(User.class_id == class_id)
            .order_by(User.user_id, AttendanceRecord.week_number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_user_and_week(
        self,
        user_id: int,
        week_number: int,
    ) -> AttendanceRecord | None:
        stmt = select(AttendanceRecord).where(
            AttendanceRecord.user_id == user_id,
            AttendanceRecord.week_number == week_number,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(self, record: AttendanceRecord) -> AttendanceRecord:
        if record.week_number is None:
            return await self.create(record)

        existing = await self.get_by_user_and_week(record.user_id, record.week_number)
        if existing is None:
            return await self.create(record)

        existing.attendance_date = record.attendance_date
        existing.status = record.status
        existing.note = record.note
        return await self.update(existing)
