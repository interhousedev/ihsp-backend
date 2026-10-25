"""ORM model of academic.assessments."""

import datetime as dt
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Assessment(IdMixin, TimestampMixin, Base):
    """A midterm or final control of a subject for an audience on a date.

    ``control`` is the control week of the term it belongs to; ``tentative`` is a
    date nobody in charge has confirmed (EMIS outside a control week, a head student).
    """

    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint("cardinality(audience) > 0", name="audience_not_empty"),
        Index("ix_assessments_date", "date"),
        Index("ix_assessments_subject_id", "subject_id"),
        Index("ix_assessments_audience", "audience", postgresql_using="gin"),
        Index(
            "uq_assessments_emis_lesson_id",
            "lesson_id",
            unique=True,
            postgresql_where=text("source = 'emis' AND lesson_id IS NOT NULL"),
        ),
        {"schema": "academic"},
    )

    subject_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.subjects.id"))
    audience: Mapped[list[str]] = mapped_column(ARRAY(Text))
    kind: Mapped[str] = mapped_column(
        Enum(
            "midterm",
            "final",
            "other",
            name="kind",
            native_enum=False,
            create_constraint=True,
        )
    )
    title: Mapped[str] = mapped_column(Text, server_default=text("''"))
    date: Mapped[dt.date] = mapped_column(Date)
    lesson_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.lessons.id", ondelete="SET NULL")
    )
    starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    room: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum(
            "planned",
            "tentative",
            "cancelled",
            name="status",
            native_enum=False,
            create_constraint=True,
        )
    )
    source: Mapped[str] = mapped_column(
        Enum(
            "teacher",
            "admin",
            "emis",
            "head_student",
            name="source",
            native_enum=False,
            create_constraint=True,
        )
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    control: Mapped[str | None] = mapped_column(
        Enum(
            "midterm_1",
            "midterm_2",
            "final",
            name="control",
            native_enum=False,
            create_constraint=True,
        )
    )
