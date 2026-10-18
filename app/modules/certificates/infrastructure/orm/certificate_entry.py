"""ORM models of certificates.entries and certificates.entry_files."""

from datetime import date
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CertificateEntryRow(IdMixin, TimestampMixin, Base):
    """A certificate of one student."""

    __tablename__ = "entries"
    __table_args__ = (
        Index("ix_entries_student_id", "student_id"),
        Index("ix_entries_type_id", "type_id"),
        Index(
            "uq_entries_student_type_serial",
            "student_id",
            "type_id",
            "serial",
            unique=True,
            postgresql_where=text("serial IS NOT NULL"),
        ),
        {"schema": "certificates"},
    )

    student_id: Mapped[UUID] = mapped_column(Uuid)
    type_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("certificates.types.id", ondelete="RESTRICT")
    )
    level: Mapped[str | None] = mapped_column(String(40))
    score: Mapped[float | None] = mapped_column(Float)
    percent: Mapped[float | None] = mapped_column(Float)
    subject: Mapped[str | None] = mapped_column(String(255))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    serial: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(10), server_default=text("'manual'"))
    issued_at: Mapped[date | None]
    expires_at: Mapped[date | None]
    custom_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )


class CertificateEntryFileRow(TimestampMixin, Base):
    """A file attached to an entry; ``file_id`` points into the files module."""

    __tablename__ = "entry_files"
    __table_args__ = (
        Index("ix_entry_files_entry_id", "entry_id"),
        {"schema": "certificates"},
    )

    file_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    entry_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("certificates.entries.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int]
    content_type: Mapped[str] = mapped_column(String(127))
