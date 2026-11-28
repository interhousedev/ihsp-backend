"""ORM model of notebooks.question_bank."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class QuestionBankRow(IdMixin, TimestampMixin, Base):
    """A question kept per EMIS subject and topic."""

    __tablename__ = "question_bank"
    __table_args__ = (
        CheckConstraint("difficulty IN ('easy', 'medium', 'hard')", name="difficulty"),
        CheckConstraint("origin IN ('ai', 'teacher')", name="origin"),
        CheckConstraint("visibility IN ('teacher', 'subject')", name="visibility"),
        Index("ix_question_bank_emis_subject_id_topic", "emis_subject_id", "topic"),
        Index("ix_question_bank_owner_id", "owner_id"),
        {"schema": "notebooks"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    emis_subject_id: Mapped[int] = mapped_column(Integer)
    topic: Mapped[str] = mapped_column(String(255))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    options: Mapped[list[Any]] = mapped_column(JSONB)
    explanation: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(8))
    origin: Mapped[str] = mapped_column(String(8))
    visibility: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
