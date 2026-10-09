"""ORM model of academic.timetable_entries."""

from datetime import date
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class TimetableEntry(IdMixin, TimestampMixin, Base):
    """A weekly recurring slot of a term; lessons are generated from it."""

    __tablename__ = "timetable_entries"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 1 AND 6", name="weekday"),
        CheckConstraint("period >= 1", name="period"),
        CheckConstraint("cardinality(audience) > 0", name="audience_not_empty"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="valid_range"
        ),
        Index(
            "ix_timetable_entries_term_id_weekday_period",
            "term_id",
            "weekday",
            "period",
        ),
        Index("ix_timetable_entries_teacher_id", "teacher_id"),
        Index("ix_timetable_entries_audience", "audience", postgresql_using="gin"),
        {"schema": "academic"},
    )

    term_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.terms.id"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    period: Mapped[int] = mapped_column(SmallInteger)
    week_parity: Mapped[str] = mapped_column(
        Enum(
            "every",
            "odd",
            "even",
            name="week_parity",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'every'"),
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.subjects.id"))
    teacher_id: Mapped[UUID | None] = mapped_column(Uuid)
    room_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("academic.rooms.id"))
    audience: Mapped[list[str]] = mapped_column(ARRAY(Text))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(
        Enum(
            "manual",
            "emis",
            name="source",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'manual'"),
    )
