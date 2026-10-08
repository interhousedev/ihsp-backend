"""ORM model of lms.step_states."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class StepState(IdMixin, TimestampMixin, Base):
    """A student's progress in one step, keyed by the stable step id."""

    __tablename__ = "step_states"
    __table_args__ = (
        UniqueConstraint("user_id", "step_id", name="uq_step_states_user_step"),
        Index("ix_step_states_step_id", "step_id"),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    step_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("lms.course_steps.id"))
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cards: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
