"""ORM models of academic.work_off_templates and academic.work_offs (WO-1, WO-3)."""

from datetime import date, datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column


class WorkOffTemplate(IdMixin, TimestampMixin, Base):
    """A teacher's default work-off task text."""

    __tablename__ = "work_off_templates"
    __table_args__ = (
        CheckConstraint("char_length(text) BETWEEN 1 AND 1000", name="text_length"),
        Index("ix_work_off_templates_teacher_id", "teacher_id"),
        {"schema": "academic"},
    )

    teacher_id: Mapped[UUID] = mapped_column(Uuid)
    text: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false())


class WorkOff(IdMixin, TimestampMixin, Base):
    """A work-off task of one absent student for one lesson."""

    __tablename__ = "work_offs"
    __table_args__ = (
        UniqueConstraint(
            "lesson_id", "student_id", name="uq_work_offs_lesson_id_student_id"
        ),
        CheckConstraint("status IN ('assigned', 'done')", name="status"),
        CheckConstraint("char_length(text) BETWEEN 1 AND 2000", name="text_length"),
        Index("ix_work_offs_student_id_status", "student_id", "status"),
        {"schema": "academic"},
    )

    lesson_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.lessons.id", ondelete="CASCADE")
    )
    student_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.students.user_id")
    )
    assigned_by: Mapped[UUID] = mapped_column(Uuid)
    template_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.work_off_templates.id", ondelete="SET NULL")
    )
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="assigned")
    due_date: Mapped[date | None] = mapped_column(Date)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
