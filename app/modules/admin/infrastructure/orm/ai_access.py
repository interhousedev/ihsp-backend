"""ORM model of admin.ai_access_restrictions (AI scopes revoked from one user)."""

from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import Boolean, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class AiAccessRow(TimestampMixin, Base):
    """One user's revoked AI scopes; a user without a row has none revoked."""

    __tablename__ = "ai_access_restrictions"
    __table_args__ = {"schema": "admin"}

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ai_chat_blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ai_notebooks_blocked: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
