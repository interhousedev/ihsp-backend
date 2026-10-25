"""ORM model of academic.temporary_marks, the temporary gradebook (TMP-1)."""

import datetime as dt
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column


class TemporaryMark(IdMixin, TimestampMixin, Base):
    """A lesson mark the teacher keeps on the platform until it is in EMIS."""

    __tablename__ = "temporary_marks"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "student_id", name="uq_temporary_marks_lesson_id_student_id"
        ),
        CheckConstraint("value BETWEEN 2 AND 5", name="value"),
        CheckConstraint(
            "comment IS NULL OR char_length(comment) BETWEEN 1 AND 500",
            name="comment_length",
        ),
        Index(
            "ix_temporary_marks_student_id_subject_id_date",
            "student_id",
            "subject_id",
            "date",
        ),
        {"schema": "academic"},
    )

    lesson_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.lessons.id", ondelete="CASCADE")
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.subjects.id"))
    # The lesson date, copied so reconciliation with EMIS marks needs no join.
    date: Mapped[dt.date] = mapped_column(Date)
    value: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[UUID] = mapped_column(Uuid)
