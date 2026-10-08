"""ORM model of id.telegram_links."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class TelegramLink(IdMixin, TimestampMixin, Base):
    """A linked Telegram account; deleting the row unlinks it."""

    __tablename__ = "telegram_links"
    __table_args__ = (
        UniqueConstraint("telegram_user_id", name="uq_telegram_links_telegram_user_id"),
        Index("ix_telegram_links_user_id", "user_id"),
        {"schema": "id"},
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    otp_delivery: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(255))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
