"""ORM model of id.mcp_call_log."""

from typing import Any
from uuid import UUID

from app.modules.identity.infrastructure.orm.types import InetStr
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class McpCallLogRow(IdMixin, TimestampMixin, Base):
    """One MCP tool call, redacted (allow-list); purged after the retention period.

    ``connector_id`` has no foreign key and the name is copied: the trace stays readable
    after a connector is deleted. Deleting the user removes the rows.
    """

    __tablename__ = "mcp_call_log"
    __table_args__ = (
        Index("ix_mcp_call_log_user_id_created_at", "user_id", "created_at"),
        Index("ix_mcp_call_log_connector_id_created_at", "connector_id", "created_at"),
        Index("ix_mcp_call_log_created_at", "created_at"),
        Index("ix_mcp_call_log_outcome_created_at", "outcome", "created_at"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("id.users.id", ondelete="CASCADE")
    )
    connector_id: Mapped[UUID | None] = mapped_column(Uuid)
    connector_name: Mapped[str | None] = mapped_column(String(255))
    client_id: Mapped[str | None] = mapped_column(String(255))
    server: Mapped[str] = mapped_column(String(16))
    tool: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100))
    read_only: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_id: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(InetStr)
