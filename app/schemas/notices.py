"""공지사항(notices) API의 Pydantic 스키마."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, field_serializer

_IS_NEW_WITHIN = timedelta(days=3)


class NoticeItem(BaseModel):
    """GET /student/notices 응답의 공지 항목."""

    notice_id: int
    title: str
    content: str
    author_name: str
    created_at: datetime | None
    is_new: bool

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class StudentNoticeListResponse(BaseModel):
    """GET /student/notices 성공 응답."""

    total_count: int
    notices: list[NoticeItem]


class TeacherNoticeCreateRequest(BaseModel):
    """POST /teacher/notices 요청 바디."""

    title: str
    content: str
    class_id: int | None


class TeacherNoticeCreateResponse(BaseModel):
    """POST /teacher/notices 성공 응답."""

    notice_id: int
    created_at: datetime | None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_is_new(created_at: datetime | None, *, now: datetime | None = None) -> bool:
    """최근 3일 이내 작성 공지인지 판별한다."""

    if created_at is None:
        return False

    reference = now or datetime.now(UTC)
    created = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    return reference - created < _IS_NEW_WITHIN
