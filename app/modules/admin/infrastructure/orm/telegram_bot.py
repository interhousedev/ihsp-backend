"""ORM models of admin.telegram_bots and admin.telegram_bot_members."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class TelegramBotRow(IdMixin, TimestampMixin, Base):
    """One registered bot; the token is in Vault, only its last 4 characters here."""

    __tablename__ = "telegram_bots"
    __table_args__ = (
        Index(
            "uq_telegram_bots_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        {"schema": "admin"},
    )

    name: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(64))
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    token_hint: Mapped[str] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)


class TelegramBotMemberRow(TimestampMixin, Base):
    """A Telegram user who wrote to a bot; `user_id` once the account is linked."""

    __tablename__ = "telegram_bot_members"
    __table_args__ = (
        Index("ix_telegram_bot_members_user_id", "user_id"),
        {"schema": "admin"},
    )

    bot_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("admin.telegram_bots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
