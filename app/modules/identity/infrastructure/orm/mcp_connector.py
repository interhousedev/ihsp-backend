"""ORM model of id.mcp_connectors."""

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


class McpConnector(IdMixin, TimestampMixin, Base):
    """An AI client connected to an MCP server on behalf of a user."""

    __tablename__ = "mcp_connectors"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mcp_connectors_token_hash"),
        Index("ix_mcp_connectors_user_id", "user_id"),
        Index("ix_mcp_connectors_hydra_client_id", "hydra_client_id"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    server: Mapped[str] = mapped_column(
        Enum(
            "student",
            "lms",
            "admin",
            name="server",
            native_enum=False,
            create_constraint=True,
        )
    )
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    course_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(Uuid))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    token_prefix: Mapped[str | None] = mapped_column(String(16))
    hydra_client_id: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
