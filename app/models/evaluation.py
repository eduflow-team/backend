from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    evaluation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("submissions.submission_id", name="fk_evaluations_submission"),
        nullable=False,
    )
    factuality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    social_impact_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_understanding_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_literacy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problem_solving_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_ethics_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_plan_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_literacy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    misconception_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
