"""ORM model of media.media_jobs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class MediaJobRow(Base):
    """A voice-over / video job of a teacher."""

    __tablename__ = "media_jobs"
    __table_args__ = (
        Index("ix_media_jobs_owner_hash", "owner_id", "script_hash"),
        Index("ix_media_jobs_owner_created", "owner_id", "created_at"),
        {"schema": "media"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(24))
    script: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB)
    script_hash: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    group_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    audio_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    captions_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    file_id: Mapped[UUID | None] = mapped_column(Uuid)
    storage_key: Mapped[str | None] = mapped_column(String(300))
    segments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    duration_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
