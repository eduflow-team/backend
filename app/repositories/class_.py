from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_ import Class
from app.repositories.base import BaseRepository


class ClassRepository(BaseRepository[Class]):
    model = Class

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_all(self) -> list[Class]:
        stmt = select(Class).order_by(Class.grade, Class.class_number)
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_teacher(self, teacher_id: int) -> list[Class]:
        stmt = (
            select(Class)
            .where(Class.teacher_id == teacher_id)
            .order_by(Class.grade, Class.class_number)
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
