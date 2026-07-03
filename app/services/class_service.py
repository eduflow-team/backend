"""학급 목록 조회 관련 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_ import Class
from app.repositories.class_ import ClassRepository


class ClassService:
    def __init__(self, session: AsyncSession) -> None:
        self.class_repository = ClassRepository(session)

    async def list_classes(self) -> list[Class]:
        return await self.class_repository.list_all()
