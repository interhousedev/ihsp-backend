"""ORM model of academic.marks."""

import datetime as dt
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Mark(IdMixin, TimestampMixin, Base):
    """A mark synced from EMIS; identity is the natural key (EMIS has no IDs)."""

    __tablename__ = "marks"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "subject_id",
            "semester",
            "type",
            "date",
            "value",
            "ordinal",
            name="uq_marks_natural_key",
        ),
        CheckConstraint("semester BETWEEN 1 AND 4", name="semester"),
        CheckConstraint("value BETWEEN 2 AND 5", name="value"),
        CheckConstraint("ordinal >= 1", name="ordinal"),
        Index("ix_marks_student_id_date", "student_id", "date"),
        Index("ix_marks_lesson_id", "lesson_id"),
        {"schema": "academic"},
    )

    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.subjects.id"))
    semester: Mapped[int] = mapped_column(SmallInteger)
    type: Mapped[str] = mapped_column(
        Enum(
            "lesson",
            "midterm",
            "final",
            name="type",
            native_enum=False,
            create_constraint=True,
        )
    )
    value: Mapped[int] = mapped_column(SmallInteger)
    date: Mapped[dt.date] = mapped_column(Date)
    ordinal: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    lesson_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.lessons.id", ondelete="SET NULL")
    )
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
