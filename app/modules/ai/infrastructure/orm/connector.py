"""ORM model of ai.connectors (provider endpoints; keys live in Vault, not here)."""

from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import Boolean, CheckConstraint, String, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column


class ConnectorRow(TimestampMixin, Base):
    """A connector added or overridden by an administrator."""

    __tablename__ = "connectors"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('openrouter', 'anthropic', 'openai_compatible', 'exa')",
            name="kind",
        ),
        {"schema": "ai"},
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(120))
    base_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    has_secret: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    secret_last4: Mapped[str | None] = mapped_column(String(4))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
