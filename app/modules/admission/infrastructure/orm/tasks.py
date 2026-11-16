"""The tasks of a student."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.admission.domain.tasks import PRIORITIES, SOURCES, STATUSES
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    LockMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import CheckConstraint, Date, DateTime, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class TaskRow(IdMixin, CreatedMixin, UpdatedMixin, LockMixin, Base):
    """A task; steps and links are JSON lists."""

    __tablename__ = "tasks"
    __table_args__ = (
        check_in("status", STATUSES),
        check_in("priority", PRIORITIES),
        check_in("created_by", SOURCES),
        CheckConstraint(
            "start_date IS NULL OR start_date >= DATE '2000-01-01'",
            name="start_year",
        ),
        CheckConstraint(
            "deadline IS NULL OR deadline >= DATE '2000-01-01'", name="deadline_year"
        ),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(11), server_default="planned")
    priority: Mapped[str] = mapped_column(String(6), server_default="medium")
    start_date: Mapped[date | None] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[str] = mapped_column(String(10), server_default="student")
    creator_id: Mapped[UUID | None] = mapped_column(Uuid)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
