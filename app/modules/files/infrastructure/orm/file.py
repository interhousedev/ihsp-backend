"""ORM model of files.files."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column


class File(IdMixin, TimestampMixin, Base):
    """Metadata of an object in S3; the bytes are never in the database."""

    __tablename__ = "files"
    __table_args__ = (
        UniqueConstraint("key", name="uq_files_key"),
        Index("ix_files_owner_id_scope_term_id", "owner_id", "scope", "term_id"),
        Index("ix_files_term_id_status", "term_id", "status"),
        Index("ix_files_expires_at", "expires_at"),
        Index("ix_files_status_created_at", "status", "created_at"),
        Index("ix_files_search_vector", "search_vector", postgresql_using="gin"),
        {"schema": "files"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    scope: Mapped[str] = mapped_column(
        Enum(
            "student",
            "staff",
            "course",
            "mail",
            "system",
            name="scope",
            native_enum=False,
            create_constraint=True,
        )
    )
    key: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    checksum: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "processing",
            "ready",
            "rejected",
            "deleted",
            name="status",
            native_enum=False,
            create_constraint=True,
        )
    )
    reject_reason: Mapped[str | None] = mapped_column(String(255))
    # The column is called "metadata"; that attribute name is reserved by SQLAlchemy.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    text_bytes: Mapped[int | None] = mapped_column(Integer)
    search_vector: Mapped[Any | None] = mapped_column(TSVECTOR)
    term_id: Mapped[UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
