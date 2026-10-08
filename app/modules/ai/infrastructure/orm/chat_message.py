"""ORM model of ai.chat_messages."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ChatMessage(IdMixin, TimestampMixin, Base):
    """One message of a chat; assistant messages carry their tool calls."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "seq", name="uq_chat_messages_chat_id_seq"),
        Index("ix_chat_messages_file_ids", "file_ids", postgresql_using="gin"),
        {"schema": "ai"},
    )

    chat_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai.chats.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(
        Enum(
            "user",
            "assistant",
            name="role",
            native_enum=False,
            create_constraint=True,
        )
    )
    content: Mapped[Any] = mapped_column(JSONB)
    file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
