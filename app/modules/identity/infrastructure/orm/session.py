"""ORM model of id.sessions."""

from datetime import datetime
from uuid import UUID

from app.modules.identity.infrastructure.orm.types import InetStr
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Session(IdMixin, TimestampMixin, Base):
    """One login of a user in the ID Service login app or the mini app."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("hydra_sid", name="uq_sessions_hydra_sid"),
        Index("ix_sessions_user_id", "user_id"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    hydra_sid: Mapped[str | None] = mapped_column(String(255))
    amr: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    mfa_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str] = mapped_column(InetStr)
    user_agent: Mapped[str] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
