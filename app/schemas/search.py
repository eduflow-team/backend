"""통합 검색(search) API의 Pydantic 스키마."""

from datetime import UTC, datetime

from pydantic import BaseModel, field_serializer


class SearchAssignmentItem(BaseModel):
    """검색 결과의 과제 항목."""

    assignment_id: int
    title: str | None
    stage: int | None


class SearchStudentItem(BaseModel):
    """검색 결과의 학생 항목."""

    student_id: int
    student_name: str
    email: str | None


class SearchNoticeItem(BaseModel):
    """검색 결과의 공지 항목."""

    notice_id: int
    title: str | None
    created_at: datetime | None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SearchResults(BaseModel):
    """카테고리별 검색 결과."""

    assignments: list[SearchAssignmentItem]
    students: list[SearchStudentItem]
    notices: list[SearchNoticeItem]


class SearchResponse(BaseModel):
    """GET /search 성공 응답."""

    keyword: str
    search_results: SearchResults
