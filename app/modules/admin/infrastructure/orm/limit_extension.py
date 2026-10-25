"""ORM model of admin.limit_extensions (per-user raises of the AI limits)."""

from datetime import date
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import CheckConstraint, Date, SmallInteger, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class LimitExtensionRow(TimestampMixin, Base):
    """One student's extension: a multiplier and/or explicit values, until a date."""

    __tablename__ = "limit_extensions"
    __table_args__ = (
        CheckConstraint(
            "multiplier IS NULL OR multiplier BETWEEN 2 AND 10",
            name="multiplier",
        ),
        {"schema": "admin"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    multiplier: Mapped[int | None] = mapped_column(SmallInteger)
    values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    expires_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(500), server_default=text("''"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
