"""ORM model of admin.platform_settings."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class PlatformSetting(TimestampMixin, Base):
    """One runtime-adjustable platform setting (key to JSON value)."""

    __tablename__ = "platform_settings"
    __table_args__ = ({"schema": "admin"},)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
