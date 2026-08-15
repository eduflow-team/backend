"""과제 마감일 등 공통 datetime 유틸."""

from datetime import UTC, datetime

from app.core.exceptions import InvalidAssignmentDueAtError


def normalize_assignment_due_at(value: datetime) -> datetime:
    """Form/ISO 입력을 UTC aware로 정규화하고, 과거 시각이면 400을 낸다."""
    if value.tzinfo is None:
        due = value.replace(tzinfo=UTC)
    else:
        due = value.astimezone(UTC)
    if due <= datetime.now(UTC):
        raise InvalidAssignmentDueAtError()
    return due


def serialize_utc_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
