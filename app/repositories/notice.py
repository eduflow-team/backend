from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notice import Notice
from app.repositories.base import BaseRepository


class NoticeRepository(BaseRepository[Notice]):
    model = Notice

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_by_class(self, class_id: int | None = None) -> list[Notice]:
        stmt = select(Notice).order_by(Notice.created_at.desc())
        if class_id is not None:
            stmt = stmt.where(or_(Notice.class_id == class_id, Notice.class_id.is_(None)))
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_by_keyword(self, keyword: str, *, limit: int = 20) -> list[Notice]:
        stmt = (
            select(Notice)
            .where(
                or_(
                    Notice.title.ilike(f"%{keyword}%"),
                    Notice.content.ilike(f"%{keyword}%"),
                )
            )
            .order_by(Notice.created_at.desc())
            .limit(limit)
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
