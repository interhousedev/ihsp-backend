"""ORM model of academic.homework_submissions."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column


class HomeworkSubmission(IdMixin, TimestampMixin, Base):
    """The files a student handed in for a lesson's homework (one per student)."""

    __tablename__ = "homework_submissions"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "student_id", name="uq_homework_submissions_lesson_student"
        ),
        CheckConstraint("cardinality(file_ids) BETWEEN 1 AND 10", name="file_count"),
        CheckConstraint("char_length(comment) <= 2000", name="comment_length"),
        Index("ix_homework_submissions_lesson_id", "lesson_id"),
        {"schema": "academic"},
    )

    lesson_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.lessons.id"))
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    file_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
