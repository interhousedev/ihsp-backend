"""ORM models of the privacy schema."""

from datetime import date, datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import BigInteger, Date, DateTime, Index, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class ErasureRequestRow(IdMixin, TimestampMixin, Base):
    """A user's request to erase the account and the personal data."""

    __tablename__ = "erasure_requests"
    __table_args__ = (
        Index(
            "uq_erasure_requests_open",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending_review', 'approved')"),
        ),
        Index("ix_erasure_requests_status", "status", "requested_at"),
        Index("ix_erasure_requests_user_id", "user_id"),
        {"schema": "privacy"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    closes_on: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExportRow(IdMixin, TimestampMixin, Base):
    """A data export of one user (the archive lives in object storage)."""

    __tablename__ = "exports"
    __table_args__ = (
        Index("ix_exports_user_id", "user_id", "created_at"),
        {"schema": "privacy"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    storage_key: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)
