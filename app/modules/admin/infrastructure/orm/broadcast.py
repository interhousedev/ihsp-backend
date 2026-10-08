"""ORM model of admin.broadcasts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ARRAY, DateTime, Enum, Index, String, Text, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Broadcast(IdMixin, TimestampMixin, Base):
    """An announcement sent by Administration to an audience."""

    __tablename__ = "broadcasts"
    __table_args__ = (
        Index("ix_broadcasts_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_broadcasts_media_file_ids", "media_file_ids", postgresql_using="gin"),
        {"schema": "admin"},
    )

    author_id: Mapped[UUID] = mapped_column(Uuid)
    created_via: Mapped[str] = mapped_column(
        Enum(
            "ui",
            "assistant",
            name="created_via",
            native_enum=False,
            create_constraint=True,
        )
    )
    title: Mapped[str] = mapped_column(String(255))
    # The attribute is called "text", so SQL text() is imported as sql_text.
    text: Mapped[str] = mapped_column(Text)
    media_file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=sql_text("'{}'")
    )
    audience: Mapped[dict[str, Any]] = mapped_column(JSONB)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum(
            "draft",
            "scheduled",
            "sending",
            "sent",
            "cancelled",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=sql_text("'draft'"),
    )
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
