from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Class(Base):
    __tablename__ = "classes"

    class_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    class_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teacher_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", name="fk_classes_teacher", use_alter=True),
        nullable=True,
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
