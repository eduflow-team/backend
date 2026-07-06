"""성적·기록(records) API의 Pydantic 스키마."""

from typing import Any

from pydantic import BaseModel


class StudentRecordItem(BaseModel):
    """GET /student/records 응답의 단계별 기록 항목."""

    stage: int
    title: str | None
    highest_score: int | None
    attempts_count: int
    ai_feedback: str | None
    metadata: dict[str, Any] | None


class StudentRecordsResponse(BaseModel):
    """GET /student/records 성공 응답."""

    class_total_average: float
    records: list[StudentRecordItem]
