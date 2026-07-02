from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Stage1AssignmentDetail(Base):
    __tablename__ = "stage1_assignment_details"

    detail_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_stage1_details_assignment"),
        nullable=False,
    )
    parameter_guide: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    default_parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    guideline: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hallucination_types: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hallucination_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_hallucination_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Stage2AssignmentDetail(Base):
    __tablename__ = "stage2_assignment_details"

    detail_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_stage2_details_assignment"),
        nullable=False,
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.document_id", name="fk_stage2_details_document"),
        nullable=False,
    )
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hallucinated_ai_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    hallucination_types: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    expected_error_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Stage2ErrorAnswer(Base):
    __tablename__ = "stage2_error_answers"

    answer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assignments.assignment_id", name="fk_stage2_answers_assignment"),
        nullable=False,
    )
    detail_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("stage2_assignment_details.detail_id", name="fk_stage2_answers_detail"),
        nullable=True,
    )
    error_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    hallucination_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
