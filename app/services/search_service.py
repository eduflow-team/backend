"""통합 검색(search) 도메인 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidSearchKeywordError,
    InvalidTokenError,
    SearchAccessForbiddenError,
)
from app.models.assignment import Assignment
from app.models.notice import Notice
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.class_ import ClassRepository
from app.repositories.notice import NoticeRepository
from app.repositories.user import UserRepository
from app.schemas.search import (
    SearchAssignmentItem,
    SearchNoticeItem,
    SearchResponse,
    SearchResults,
    SearchStudentItem,
)

_SEARCH_RESULT_LIMIT = 20
_MIN_KEYWORD_LENGTH = 2


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.notice_repository = NoticeRepository(session)

    async def search(self, user_id: int, keyword: str) -> SearchResponse:
        user = await self._get_authorized_user(user_id)
        normalized_keyword = keyword.strip()
        if len(normalized_keyword) < _MIN_KEYWORD_LENGTH:
            raise InvalidSearchKeywordError()

        if user.role == "STUDENT":
            assignments, students, notices = await self._search_for_student(
                user, normalized_keyword
            )
        else:
            assignments, students, notices = await self._search_for_teacher(
                user, normalized_keyword
            )

        return SearchResponse(
            keyword=normalized_keyword,
            search_results=SearchResults(
                assignments=assignments,
                students=students,
                notices=notices,
            ),
        )

    async def _search_for_student(
        self, user: User, keyword: str
    ) -> tuple[list[SearchAssignmentItem], list[SearchStudentItem], list[SearchNoticeItem]]:
        class_id = user.class_id

        assignment_candidates = await self.assignment_repository.search_by_title(
            keyword, limit=_SEARCH_RESULT_LIMIT
        )
        assignments = [
            self._build_assignment_item(assignment)
            for assignment in assignment_candidates
            if class_id is not None and assignment.class_id == class_id
        ]

        student_candidates = await self.user_repository.search_by_name(
            keyword, limit=_SEARCH_RESULT_LIMIT
        )
        students = [
            self._build_student_item(student)
            for student in student_candidates
            if student.role == "STUDENT"
            and class_id is not None
            and student.class_id == class_id
        ]

        notice_candidates = await self.notice_repository.search_by_keyword(
            keyword, limit=_SEARCH_RESULT_LIMIT
        )
        notices = [
            self._build_notice_item(notice)
            for notice in notice_candidates
            if self._is_notice_visible_to_student(notice, class_id)
        ]

        return assignments, students, notices

    async def _search_for_teacher(
        self, user: User, keyword: str
    ) -> tuple[list[SearchAssignmentItem], list[SearchStudentItem], list[SearchNoticeItem]]:
        class_ids = await self._get_teacher_class_ids(user)
        class_id_set = set(class_ids)

        assignment_candidates = await self.assignment_repository.search_by_title(
            keyword, limit=_SEARCH_RESULT_LIMIT
        )
        assignments = [
            self._build_assignment_item(assignment)
            for assignment in assignment_candidates
            if assignment.class_id in class_id_set
        ]

        student_candidates = await self.user_repository.search_by_name(
            keyword, limit=_SEARCH_RESULT_LIMIT
        )
        students = [
            self._build_student_item(student)
            for student in student_candidates
            if student.role == "STUDENT"
            and student.class_id is not None
            and student.class_id in class_id_set
        ]

        notice_candidates = await self.notice_repository.search_by_keyword(
            keyword, limit=_SEARCH_RESULT_LIMIT
        )
        notices = [
            self._build_notice_item(notice)
            for notice in notice_candidates
            if self._is_notice_visible_to_teacher(notice, class_id_set)
        ]

        return assignments, students, notices

    async def _get_authorized_user(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role not in {"STUDENT", "TEACHER"}:
            raise SearchAccessForbiddenError()

        return user

    async def _get_teacher_class_ids(self, teacher: User) -> list[int]:
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = {c.class_id for c in classes}
        if teacher.class_id is not None:
            class_ids.add(teacher.class_id)
        return sorted(class_ids)

    def _is_notice_visible_to_student(self, notice: Notice, class_id: int | None) -> bool:
        if notice.class_id is None:
            return True
        return class_id is not None and notice.class_id == class_id

    def _is_notice_visible_to_teacher(
        self, notice: Notice, class_id_set: set[int]
    ) -> bool:
        if notice.class_id is None:
            return True
        return notice.class_id in class_id_set

    def _build_assignment_item(self, assignment: Assignment) -> SearchAssignmentItem:
        return SearchAssignmentItem(
            assignment_id=assignment.assignment_id,
            title=assignment.title,
            stage=assignment.stage,
        )

    def _build_student_item(self, student: User) -> SearchStudentItem:
        return SearchStudentItem(
            student_id=student.user_id,
            student_name=student.name or "",
            email=student.email,
        )

    def _build_notice_item(self, notice: Notice) -> SearchNoticeItem:
        return SearchNoticeItem(
            notice_id=notice.notice_id,
            title=notice.title,
            created_at=notice.created_at,
        )
