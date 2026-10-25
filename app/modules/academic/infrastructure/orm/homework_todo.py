"""ORM model of academic.homework_todos."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column


class HomeworkTodo(IdMixin, TimestampMixin, Base):
    """A student's own done flag and private note for a lesson's homework."""

    __tablename__ = "homework_todos"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "lesson_id", name="uq_homework_todos_student_lesson"
        ),
        CheckConstraint("char_length(note) <= 1000", name="note_length"),
        Index("ix_homework_todos_lesson_id", "lesson_id"),
        {"schema": "academic"},
    )

    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    lesson_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.lessons.id"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
