from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StudentAssignmentStatus(Base):
    __tablename__ = "student_assignment_status"
    __table_args__ = (
        UniqueConstraint("user_id", "assignment_id", name="uq_student_assignment"),
    )

    status_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", name="fk_status_user"), nullable=False
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_status_assignment"),
        nullable=False,
    )
    progress_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    best_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_literacy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bias_found_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    learning_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
