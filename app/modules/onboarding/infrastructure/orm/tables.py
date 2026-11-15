"""ORM model of onboarding.onboarding_progress."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base

from sqlalchemy import DateTime, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class OnboardingProgressRow(Base):
    """What a user finished in the onboarding wizard."""

    __tablename__ = "onboarding_progress"
    __table_args__ = ({"schema": "onboarding"},)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    certificates_prompt_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
