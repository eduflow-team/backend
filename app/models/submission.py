from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Submission(Base):
    __tablename__ = "submissions"

    submission_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", name="fk_submissions_user"), nullable=False
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_submissions_assignment"),
        nullable=False,
    )
    stage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    current_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_final: Mapped[bool | None] = mapped_column(Boolean, server_default="false", nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Stage1Attempt(Base):
    __tablename__ = "stage1_attempts"

    attempt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", name="fk_stage1_attempts_user"), nullable=False
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_stage1_attempts_assignment"),
        nullable=False,
    )
    submission_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("submissions.submission_id", name="fk_stage1_attempts_submission"),
        nullable=True,
    )
    student_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )


class Stage2HighlightSubmission(Base):
    __tablename__ = "stage2_highlight_submissions"

    highlight_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", name="fk_stage2_highlight_user"),
        nullable=False,
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_stage2_highlight_assignment"),
        nullable=False,
    )
    submission_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("submissions.submission_id", name="fk_stage2_highlight_submission"),
        nullable=True,
    )
    highlighted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    highlight_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    correction_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )


class Stage2CorrectionSubmission(Base):
    __tablename__ = "stage2_correction_submissions"

    correction_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", name="fk_stage2_correction_user"),
        nullable=False,
    )
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_stage2_correction_assignment"),
        nullable=False,
    )
    submission_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("submissions.submission_id", name="fk_stage2_correction_submission"),
        nullable=True,
    )
    selected_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
