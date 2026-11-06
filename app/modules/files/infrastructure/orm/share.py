"""ORM models of sharing a file."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column


class FileShareRow(Base):
    """A person's access to a file; a revoked row keeps them out of the link."""

    __tablename__ = "file_shares"
    __table_args__ = (
        CheckConstraint("via IN ('direct', 'link')", name="via"),
        Index("ix_file_shares_user_id", "user_id"),
        {"schema": "files"},
    )

    file_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("files.files.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    via: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FileShareLinkRow(Base):
    """The file's one active link; only the hash of the token is stored."""

    __tablename__ = "file_share_links"
    __table_args__ = {"schema": "files"}

    file_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("files.files.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
