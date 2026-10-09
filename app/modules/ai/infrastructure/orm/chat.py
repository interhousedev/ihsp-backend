"""ORM model of ai.chats."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import DateTime, Enum, Index, SmallInteger, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Chat(IdMixin, TimestampMixin, Base):
    """A conversation with an assistant (student, Administration or course author)."""

    __tablename__ = "chats"
    __table_args__ = (
        Index("ix_chats_owner_id_last_message_at", "owner_id", "last_message_at"),
        Index("ix_chats_scope_course_id", text("(scope ->> 'course_id')")),
        {"schema": "ai"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    assistant: Mapped[str] = mapped_column(
        Enum(
            "student",
            "admin",
            "lms_author",
            name="assistant",
            native_enum=False,
            create_constraint=True,
        )
    )
    title: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    pending_approvals: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("0")
    )
    tier: Mapped[str] = mapped_column(
        Enum("fast", "smart", name="tier", native_enum=False, create_constraint=True),
        server_default=text("'fast'"),
    )
    # Author chats: {"course_id", "notebook_id"} (domain ChatScope); NULL otherwise.
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
