from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.repositories.base import BaseRepository


class AssignmentRepository(BaseRepository[Assignment]):
    model = Assignment

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_class(self, class_id: int) -> list[Assignment]:
        stmt = (
            select(Assignment)
            .where(Assignment.class_id == class_id)
            .order_by(Assignment.created_at.desc())
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_class_ids(self, class_ids: list[int]) -> list[Assignment]:
        """교사 대시보드처럼 여러 학급의 과제를 한 번에 조회할 때 사용한다."""

        if not class_ids:
            return []

        stmt = (
            select(Assignment)
            .where(Assignment.class_id.in_(class_ids))
            .order_by(Assignment.created_at.desc())
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_teacher(self, teacher_id: int) -> list[Assignment]:
        stmt = (
            select(Assignment)
            .where(Assignment.teacher_id == teacher_id)
            .order_by(Assignment.created_at.desc())
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_by_title(self, keyword: str, *, limit: int = 20) -> list[Assignment]:
        stmt = (
            select(Assignment)
            .where(Assignment.title.ilike(f"%{keyword}%"))
            .order_by(Assignment.created_at.desc())
            .limit(limit)
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
