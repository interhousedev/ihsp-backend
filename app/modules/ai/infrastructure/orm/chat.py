"""ORM model of ai.chats."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import DateTime, Enum, Index, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class Chat(IdMixin, TimestampMixin, Base):
    """A conversation with an AI assistant (student or Administration)."""

    __tablename__ = "chats"
    __table_args__ = (
        Index("ix_chats_owner_id_last_message_at", "owner_id", "last_message_at"),
        {"schema": "ai"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    assistant: Mapped[str] = mapped_column(
        Enum(
            "student",
            "admin",
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
