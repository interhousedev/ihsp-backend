"""ORM model of ai.usage_events (the usage ledger, one row per model call)."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class UsageEventRow(IdMixin, TimestampMixin, Base):
    """A model call: when, for whom (or the system), what it was and what it cost."""

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_occurred_at", "occurred_at"),
        Index("ix_usage_events_user_id_occurred_at", "user_id", "occurred_at"),
        Index("ix_usage_events_task_occurred_at", "task", "occurred_at"),
        CheckConstraint(
            "role IN ('student', 'teacher', 'admin', 'staff', 'system')",
            name="role",
        ),
        {"schema": "ai"},
    )

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[UUID | None] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(16))
    task: Mapped[str] = mapped_column(String(64))
    feature: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(255))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cached_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    # Millionths of a US dollar as the provider reports them; NULL when it says nothing.
    cost_micro: Mapped[int | None] = mapped_column(BigInteger)
    success: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    error: Mapped[str | None] = mapped_column(String(64))
