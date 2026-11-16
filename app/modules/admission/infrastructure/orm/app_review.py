"""ORM of the full application reviews."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["AppReviewRow"]


class AppReviewRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One version of a student's full application review."""

    __tablename__ = "app_reviews"
    __table_args__ = (
        check_in("status", ("queued", "running", "done", "failed")),
        UniqueConstraint("student_id", "version", name="uq_app_reviews_version"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(8), server_default="queued")
    locale: Mapped[str] = mapped_column(String(5))
    staff_visible: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    sections: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    models: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    error_code: Mapped[str | None] = mapped_column(String(40))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
