"""ORM models of academic.excuse_templates, excuses and excuse_messages."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ExcuseTemplate(IdMixin, TimestampMixin, Base):
    """A reason a student can pick; the title is kept in uz, ru and en."""

    __tablename__ = "excuse_templates"
    __table_args__ = ({"schema": "academic"},)

    code: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[dict[str, Any]] = mapped_column(JSONB)
    requires_document: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    sort: Mapped[int] = mapped_column(Integer, server_default="0")


class Excuse(IdMixin, TimestampMixin, Base):
    """A student's excuse from lessons: a request or a curator's exclusion."""

    __tablename__ = "excuses"
    __table_args__ = (
        CheckConstraint("origin IN ('request', 'curator')", name="origin"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="status",
        ),
        CheckConstraint("char_length(reason) <= 2000", name="reason_length"),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="period"),
        Index("ix_excuses_student_id_status", "student_id", "status"),
        Index("ix_excuses_status_created_at", "status", "created_at"),
        {"schema": "academic"},
    )

    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    origin: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    template_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.excuse_templates.id")
    )
    reason: Mapped[str] = mapped_column(Text, server_default="")
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    lesson_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    subject_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    created_by: Mapped[UUID] = mapped_column(Uuid)
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class ExcuseMessage(IdMixin, TimestampMixin, Base):
    """One line of an excuse's thread."""

    __tablename__ = "excuse_messages"
    __table_args__ = (
        CheckConstraint("char_length(body) <= 2000", name="body_length"),
        Index("ix_excuse_messages_excuse_id_created_at", "excuse_id", "created_at"),
        {"schema": "academic"},
    )

    excuse_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.excuses.id", ondelete="CASCADE")
    )
    author_id: Mapped[UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(Text, server_default="")
    file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
