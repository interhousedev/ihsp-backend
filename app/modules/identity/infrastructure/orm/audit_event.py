"""ORM model of id.audit_events."""

from typing import Any
from uuid import UUID

from app.modules.identity.infrastructure.orm.types import InetStr
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Index, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AuditEvent(IdMixin, TimestampMixin, Base):
    """Append-only security and administration log (kept one year).

    ``user_id`` and ``actor_id`` are plain UUIDs without foreign keys: the log
    must survive user changes and may name the system actor.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_events_type_created_at", "type", "created_at"),
        {"schema": "id"},
    )

    user_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    type: Mapped[str] = mapped_column(String(100))
    ip: Mapped[str | None] = mapped_column(InetStr)
    user_agent: Mapped[str | None] = mapped_column(Text)
    # The column is called "metadata"; that attribute name is reserved by SQLAlchemy.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
