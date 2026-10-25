"""ORM model of feedback.responses."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column


class FeedbackResponseRow(IdMixin, TimestampMixin, Base):
    """An administrator's response; ``deliveries`` is [{channel, status}]."""

    __tablename__ = "responses"
    __table_args__ = (
        Index("ix_responses_feedback_id_created_at", "feedback_id", "created_at"),
        {"schema": "feedback"},
    )

    feedback_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("feedback.items.id", ondelete="CASCADE")
    )
    author_id: Mapped[UUID] = mapped_column(Uuid)
    text: Mapped[str] = mapped_column(Text)
    channels: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), server_default=sql_text("'{}'")
    )
    deliveries: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    attachment_file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=sql_text("'{}'")
    )
