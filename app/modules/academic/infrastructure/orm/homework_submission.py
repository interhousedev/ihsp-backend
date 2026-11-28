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
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column


class HomeworkSubmission(IdMixin, TimestampMixin, Base):
    """What a student handed in for a lesson's homework and how it was reviewed."""

    __tablename__ = "homework_submissions"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "student_id", name="uq_homework_submissions_lesson_student"
        ),
        CheckConstraint("cardinality(file_ids) <= 10", name="file_count"),
        CheckConstraint(
            "cardinality(file_ids) >= 1 OR text IS NOT NULL", name="content"
        ),
        CheckConstraint("char_length(comment) <= 2000", name="comment_length"),
        CheckConstraint("char_length(text) <= 10000", name="text_length"),
        CheckConstraint(
            "review_status IN ('pending', 'returned', 'graded')",
            name="review_status",
        ),
        CheckConstraint("grade BETWEEN 2 AND 5", name="grade_range"),
        CheckConstraint(
            "review_status <> 'graded' OR grade IS NOT NULL", name="graded_has_grade"
        ),
        CheckConstraint(
            "char_length(teacher_comment) <= 2000", name="teacher_comment_length"
        ),
        Index("ix_homework_submissions_lesson_id", "lesson_id"),
        Index("ix_homework_submissions_review", "lesson_id", "review_status"),
        {"schema": "academic"},
    )

    lesson_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.lessons.id"))
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    file_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    text: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    review_status: Mapped[str] = mapped_column(
        Text, server_default=sql_text("'pending'")
    )
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    teacher_comment: Mapped[str | None] = mapped_column(Text)
    previous_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    temporary_mark_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.temporary_marks.id", ondelete="SET NULL")
    )
