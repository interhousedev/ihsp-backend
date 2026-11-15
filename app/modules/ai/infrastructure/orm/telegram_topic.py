"""ORM model of ai.telegram_topics."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class TelegramTopicRow(IdMixin, TimestampMixin, Base):
    """The forum topic of a private Telegram chat that carries one AI chat."""

    __tablename__ = "telegram_topics"
    __table_args__ = (
        Index("ux_telegram_topics_chat_id", "chat_id", unique=True),
        Index(
            "ux_telegram_topics_thread",
            "telegram_chat_id",
            "message_thread_id",
            unique=True,
        ),
        {"schema": "ai"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai.chats.id", ondelete="CASCADE")
    )
    message_thread_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(128), server_default=text("''"))
    icon_custom_emoji_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
