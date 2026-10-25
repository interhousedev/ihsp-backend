"""ORM model of id.login_cues."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base

from sqlalchemy import DateTime, Index, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column


class LoginCueRow(Base):
    """A pre-registered EMIS login; ``emis_login_enc`` is a Vault Transit ciphertext."""

    __tablename__ = "login_cues"
    __table_args__ = (
        Index(
            "ix_login_cues_group_open",
            "group_id",
            postgresql_where=text("consumed_at IS NULL"),
        ),
        {"schema": "id"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    emis_login_enc: Mapped[str] = mapped_column(Text)
    login_tail: Mapped[str] = mapped_column(String(2))
    full_name: Mapped[str] = mapped_column(String(255))
    group_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=func.now()
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_by_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    reserved_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
