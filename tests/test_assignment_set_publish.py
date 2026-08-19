"""Tests for Stage2 set publish_status assignment columns."""

from __future__ import annotations

from app.models.assignment import Assignment
from app.models.enums import AssignmentPublishStatus


def test_assignment_has_set_publish_columns() -> None:
    columns = {column.name for column in Assignment.__table__.columns}
    assert "set_id" in columns
    assert "publish_status" in columns


def test_assignment_publish_status_enum_values() -> None:
    assert AssignmentPublishStatus.DRAFT.value == "DRAFT"
    assert AssignmentPublishStatus.PUBLISHED.value == "PUBLISHED"
