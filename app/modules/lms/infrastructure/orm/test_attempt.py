"""ORM model of lms.test_attempts."""

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class TestAttempt(IdMixin, TimestampMixin, Base):
    """One attempt at a test block, graded on the exact revision the student saw."""

    __test__: ClassVar[bool] = False  # not a pytest class, despite the name
    __tablename__ = "test_attempts"
    __table_args__ = (
        Index(
            "ix_test_attempts_attempt_no",
            "user_id",
            "step_id",
            "block_id",
            "attempt_no",
            unique=True,
            postgresql_where=text("NOT is_preview"),
        ),
        Index("ix_test_attempts_step_id_submitted_at", "step_id", "submitted_at"),
        Index("ix_test_attempts_revision_id", "revision_id"),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    step_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("lms.course_steps.id"))
    revision_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("lms.step_revisions.id"))
    block_id: Mapped[str] = mapped_column(String(64))
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    is_preview: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    variant: Mapped[dict[str, Any]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    max_score: Mapped[Decimal] = mapped_column(Numeric)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    override_score: Mapped[Decimal | None] = mapped_column(Numeric)
    override_comment: Mapped[str | None] = mapped_column(String(1000))
    reviewed_by: Mapped[UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
