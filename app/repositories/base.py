from datetime import UTC, datetime
from typing import Generic, TypeVar

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @property
    def pk_attr(self) -> str:
        return inspect(self.model).primary_key[0].name

    def _apply_not_deleted(self, stmt):
        if "deleted_at" in self.model.__table__.c:
            return stmt.where(self.model.deleted_at.is_(None))
        return stmt

    async def get_by_id(self, entity_id: int) -> ModelT | None:
        stmt = select(self.model).where(getattr(self.model, self.pk_attr) == entity_id)
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: ModelT) -> ModelT:
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def soft_delete(self, entity: ModelT) -> ModelT:
        if "deleted_at" not in self.model.__table__.c:
            raise AttributeError(f"{self.model.__name__} does not support soft delete")
        entity.deleted_at = datetime.now(UTC)
        return await self.update(entity)
