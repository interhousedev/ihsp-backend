"""ORM model of id.mcp_scope_offers."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class McpScopeOffer(IdMixin, TimestampMixin, Base):
    """One user's offer of one release; the unique pair makes offers idempotent."""

    __tablename__ = "mcp_scope_offers"
    __table_args__ = (
        UniqueConstraint("user_id", "release_id", name="uq_mcp_scope_offers_user"),
        UniqueConstraint("token_hash", name="uq_mcp_scope_offers_token_hash"),
        Index("ix_mcp_scope_offers_status_expires_at", "status", "expires_at"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    release_id: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    connector_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "granted",
            "declined",
            "expired",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'pending'"),
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
