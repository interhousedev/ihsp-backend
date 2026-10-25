"""ORM models of the posts module (schema ``posts``)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from uuid_utils.compat import uuid7


class PostRow(TimestampMixin, Base):
    """posts.posts: one node of the bot post tree."""

    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint("audience IN ('guest', 'student', 'both')", name="audience"),
        CheckConstraint("(parent_id IS NULL) = is_root", name="root_parent"),
        Index("ix_posts_slug", "slug", unique=True),
        Index(
            "ix_posts_single_root",
            "is_root",
            unique=True,
            postgresql_where=text("is_root"),
        ),
        Index("ix_posts_parent_id", "parent_id"),
        {"schema": "posts"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid)
    slug: Mapped[str] = mapped_column(String(64))
    title: Mapped[dict[str, Any]] = mapped_column(JSONB)
    body: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    audience: Mapped[str] = mapped_column(String(16), server_default="both")
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    published: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_root: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    buttons: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )


class BotUserModeRow(Base):
    """posts.bot_user_modes: the /start choice (guest or student) per Telegram user."""

    __tablename__ = "bot_user_modes"
    __table_args__ = (
        CheckConstraint("mode IN ('guest', 'student')", name="mode"),
        Index("ix_bot_user_modes_telegram_user_id", "telegram_user_id", unique=True),
        {"schema": "posts"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


__all__ = ["BotUserModeRow", "PostRow"]
