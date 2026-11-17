"""Memory notes of a student's AI agent."""

from datetime import datetime
from uuid import UUID

from app.modules.admission.domain.memory_notes import CONTENT_MAX, SOURCES
from app.modules.admission.infrastructure.orm._common import (
    S,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import DateTime, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class MemoryNoteRow(IdMixin, UpdatedMixin, Base):
    """One note; only its student reads and deletes it."""

    __tablename__ = "memory_notes"
    __table_args__ = (
        check_in("source", SOURCES),
        max_len("content", CONTENT_MAX),
        Index("ix_memory_notes_student_id_created_at", "student_id", "created_at"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(9))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
