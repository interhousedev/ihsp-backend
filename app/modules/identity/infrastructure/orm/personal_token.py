"""ORM model of id.personal_tokens."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column


class PersonalTokenRow(IdMixin, TimestampMixin, Base):
    """A personal API token (hash only)."""

    __tablename__ = "personal_tokens"
    __table_args__ = (
        UniqueConstraint("hash", name="uq_personal_tokens_hash"),
        Index("ix_personal_tokens_user_id", "user_id"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
