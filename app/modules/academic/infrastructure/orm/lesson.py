"""ORM model of academic.lessons."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

_SCHEDULED = text("status = 'scheduled'")


def _period() -> Any:
    """Return the time range of a lesson used by the exclusion constraints."""
    return func.tstzrange(text("starts_at"), text("ends_at"), "[)")


class Lesson(IdMixin, TimestampMixin, Base):
    """One lesson with its homework and attendance (README -> Models -> Lesson)."""

    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint(
            "timetable_entry_id", "origin_date", name="uq_lessons_entry_origin_date"
        ),
        CheckConstraint(
            "(attendance_roster IS NULL) = (attendance_absent IS NULL)",
            name="attendance_pair",
        ),
        CheckConstraint(
            "attendance_absent <@ attendance_roster", name="attendance_subset"
        ),
        CheckConstraint(
            "attendance_late <@ attendance_roster", name="attendance_late_subset"
        ),
        CheckConstraint(
            "NOT (attendance_late && attendance_absent)",
            name="attendance_late_not_absent",
        ),
        CheckConstraint("ends_at > starts_at", name="time_range"),
        ExcludeConstraint(
            ("teacher_id", "="),
            (_period(), "&&"),
            name="ex_lessons_teacher_no_overlap",
            using="gist",
            where=_SCHEDULED,
        ),
        ExcludeConstraint(
            ("room_id", "="),
            (_period(), "&&"),
            name="ex_lessons_room_no_overlap",
            using="gist",
            where=_SCHEDULED,
        ),
        Index("ix_lessons_date", "date"),
        Index("ix_lessons_starts_at", "starts_at"),
        Index("ix_lessons_ends_at", "ends_at"),
        Index("ix_lessons_teacher_id_date", "teacher_id", "date"),
        Index("ix_lessons_audience", "audience", postgresql_using="gin"),
        Index("ix_lessons_emis_class_id", "emis_class_id"),
        Index(
            "ix_lessons_attendance_roster", "attendance_roster", postgresql_using="gin"
        ),
        Index(
            "ix_lessons_attendance_absent", "attendance_absent", postgresql_using="gin"
        ),
        {"schema": "academic"},
    )

    timetable_entry_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.timetable_entries.id", ondelete="SET NULL")
    )
    origin_date: Mapped[dt.date | None] = mapped_column(Date)
    term_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.terms.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    period: Mapped[int] = mapped_column(SmallInteger)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.subjects.id"))
    teacher_id: Mapped[UUID | None] = mapped_column(Uuid)
    room_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("academic.rooms.id"))
    topic: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[list[str]] = mapped_column(ARRAY(Text))
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Enum(
            "scheduled",
            "cancelled",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'scheduled'"),
    )
    is_overridden: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    kind: Mapped[str] = mapped_column(
        Enum(
            "lecture",
            "practice",
            "midterm",
            "final",
            "other",
            name="kind",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'other'"),
    )
    emis_class_id: Mapped[int | None] = mapped_column(BigInteger)
    emis_topic: Mapped[str | None] = mapped_column(Text)
    homework_text: Mapped[str | None] = mapped_column(Text)
    homework_due_date: Mapped[dt.date | None] = mapped_column(Date)
    homework_due_auto: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true")
    )
    homework_by: Mapped[UUID | None] = mapped_column(Uuid)
    homework_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    homework_updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    attendance_roster: Mapped[list[UUID] | None] = mapped_column(ARRAY(Uuid))
    attendance_absent: Mapped[list[UUID] | None] = mapped_column(ARRAY(Uuid))
    attendance_late: Mapped[list[UUID] | None] = mapped_column(ARRAY(Uuid))
    attendance_excused: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attendance_version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    attendance_by: Mapped[UUID | None] = mapped_column(Uuid)
    attendance_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    attendance_source: Mapped[str | None] = mapped_column(
        Enum(
            "bot",
            "staff",
            "admin",
            name="attendance_source",
            native_enum=False,
            create_constraint=True,
        )
    )
