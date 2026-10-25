"""ORM model of academic.student_sync_jobs (one initial EMIS sync per student)."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class StudentSyncJob(TimestampMixin, Base):
    """Durable state of a student's initial sync; written with the registration."""

    __tablename__ = "student_sync_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_student_sync_jobs_status",
        ),
        Index(
            "ix_student_sync_jobs_status_next_attempt",
            "status",
            "next_attempt_at",
        ),
        {"schema": "academic"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid(),
        ForeignKey("academic.students.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("0"), default=0
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    subgroup: Mapped[int | None] = mapped_column(SmallInteger)
    marks_count: Mapped[int | None] = mapped_column(Integer)
