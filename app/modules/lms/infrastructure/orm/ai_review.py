"""ORM models of lms.ai_review_sessions and lms.ai_review_messages."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AiReviewSession(IdMixin, TimestampMixin, Base):
    """One review conversation of a student about one AI review block."""

    __tablename__ = "ai_review_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'reviewed')", name="status"),
        Index("ix_ai_review_sessions_block", "step_id", "block_id", "user_id"),
        Index("ix_ai_review_sessions_user", "user_id", "id"),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    step_id: Mapped[UUID] = mapped_column(Uuid)
    block_id: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), server_default=sql("'open'"))
    submissions_used: Mapped[int] = mapped_column(Integer, server_default=sql("0"))


class AiReviewMessage(IdMixin, TimestampMixin, Base):
    """A message of an AI review conversation, already filtered for the student."""

    __tablename__ = "ai_review_messages"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'assistant')", name="role"),
        CheckConstraint("kind IN ('chat', 'question', 'review')", name="kind"),
        {"schema": "lms"},
    )

    session_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.ai_review_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str | None] = mapped_column(Text)
    openui: Mapped[str | None] = mapped_column(Text)
    history: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    attachments: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql("'[]'"))
