"""Threads and messages of the admission assistant."""

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

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AssistantThreadRow(IdMixin, CreatedMixin, Base):
    """A conversation of one student."""

    __tablename__ = "assistant_threads"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    title: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AssistantMessageRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One message; citations and actions are JSON lists."""

    __tablename__ = "assistant_messages"
    __table_args__ = (check_in("role", ("user", "assistant")), S)

    thread_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.assistant_threads.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    role: Mapped[str] = mapped_column(String(9))
    text: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
