"""공지사항(notices) 도메인 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidNoticeCreateError,
    InvalidTokenError,
    NoticesAccessForbiddenError,
    TeacherNoticeCreateForbiddenError,
)
from app.models.notice import Notice
from app.models.user import User
from app.repositories.class_ import ClassRepository
from app.repositories.notice import NoticeRepository
from app.repositories.user import UserRepository
from app.schemas.notices import (
    NoticeItem,
    StudentNoticeListResponse,
    TeacherNoticeCreateRequest,
    TeacherNoticeCreateResponse,
    compute_is_new,
)


class NoticeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notice_repository = NoticeRepository(session)
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)

    async def get_student_notices(
        self,
        user_id: int,
        *,
        page: int = 1,
        size: int = 10,
    ) -> StudentNoticeListResponse:
        user = await self._get_authorized_student(user_id)
        notices = await self.notice_repository.list_for_student(user.class_id)
        total_count = len(notices)

        start = (page - 1) * size
        page_notices = notices[start : start + size]

        author_names = await self._resolve_author_names(
            {notice.author_id for notice in page_notices}
        )

        items = [
            NoticeItem(
                notice_id=notice.notice_id,
                title=notice.title or "",
                content=notice.content or "",
                author_name=author_names.get(notice.author_id, ""),
                created_at=notice.created_at,
                is_new=compute_is_new(notice.created_at),
            )
            for notice in page_notices
        ]

        return StudentNoticeListResponse(total_count=total_count, notices=items)

    async def create_teacher_notice(
        self,
        user_id: int,
        payload: TeacherNoticeCreateRequest,
    ) -> TeacherNoticeCreateResponse:
        teacher = await self._get_authorized_teacher(user_id)

        title = payload.title.strip()
        content = payload.content.strip()
        if not title or not content:
            raise InvalidNoticeCreateError()

        notice_class_id = payload.class_id
        if notice_class_id is not None:
            allowed_class_ids = await self._get_teacher_class_ids(teacher)
            if notice_class_id not in allowed_class_ids:
                raise TeacherNoticeCreateForbiddenError()

        notice = Notice(
            author_id=teacher.user_id,
            class_id=notice_class_id,
            title=title,
            content=content,
        )
        notice = await self.notice_repository.create(notice)
        await self.session.commit()

        return TeacherNoticeCreateResponse(
            notice_id=notice.notice_id,
            created_at=notice.created_at,
        )

    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "STUDENT":
            raise NoticesAccessForbiddenError()

        return user

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "TEACHER":
            raise TeacherNoticeCreateForbiddenError()

        return user

    async def _get_teacher_class_ids(self, teacher: User) -> set[int]:
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = {c.class_id for c in classes}
        if teacher.class_id is not None:
            class_ids.add(teacher.class_id)
        return class_ids

    async def _resolve_author_names(self, author_ids: set[int]) -> dict[int, str]:
        names: dict[int, str] = {}
        for author_id in author_ids:
            author = await self.user_repository.get_by_id(author_id)
            names[author_id] = author.name if author and author.name else ""
        return names
