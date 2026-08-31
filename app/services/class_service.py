"""학급 목록 조회 관련 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DashboardAccessForbiddenError, InvalidTokenError
from app.models.class_ import Class
from app.repositories.class_ import ClassRepository
from app.repositories.user import UserRepository


class ClassService:
    def __init__(self, session: AsyncSession) -> None:
        self.class_repository = ClassRepository(session)
        self.user_repository = UserRepository(session)

    async def list_classes(self) -> list[Class]:
        return await self.class_repository.list_all()

    async def list_classes_for_teacher(self, user_id: int) -> list[Class]:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()
        if user.role != "TEACHER":
            raise DashboardAccessForbiddenError()

        classes = await self.class_repository.list_by_teacher(user.user_id)
        by_id = {item.class_id: item for item in classes}
        if user.class_id is not None and user.class_id not in by_id:
            linked = await self.class_repository.get_by_id(user.class_id)
            if linked is not None:
                by_id[linked.class_id] = linked
        return sorted(by_id.values(), key=lambda item: (item.grade or 0, item.class_number or 0))
