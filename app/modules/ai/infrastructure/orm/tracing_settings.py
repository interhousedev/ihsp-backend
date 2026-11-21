"""ORM model of ai.tracing_settings (the Langfuse project set at runtime, one row)."""

from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import Boolean, CheckConstraint, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class TracingSettingsRow(TimestampMixin, Base):
    """Host and public key of the Langfuse project; the secret key is in Vault."""

    __tablename__ = "tracing_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    host: Mapped[str] = mapped_column(String(500))
    public_key: Mapped[str] = mapped_column(String(255))
    has_secret: Mapped[bool] = mapped_column(
        Boolean, server_default="false", default=False
    )
    secret_last4: Mapped[str | None] = mapped_column(String(4))
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
