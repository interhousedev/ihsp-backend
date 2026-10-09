"""ORM models of the shared content layer: documents, their aliases and guides."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CHAR,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Document(IdMixin, TimestampMixin, Base):
    """One distinct normalized text; its passages are shared by every source of it."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_documents_content_hash"),
        {"schema": "notebooks"},
    )

    content_hash: Mapped[str] = mapped_column(CHAR(64))
    word_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    char_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    token_estimate: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    passage_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class DocumentAlias(TimestampMixin, Base):
    """A known identity of a text (`sha256:<checksum>`, `file:<id>`): skips reading."""

    __tablename__ = "document_aliases"
    __table_args__ = (
        Index("ix_document_aliases_document_id", "document_id"),
        {"schema": "notebooks"},
    )

    alias: Mapped[str] = mapped_column(String(300), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.documents.id", ondelete="CASCADE")
    )


class DocumentGuide(TimestampMixin, Base):
    """The source guide of a document in one language (written once, reused)."""

    __tablename__ = "document_guides"
    __table_args__ = ({"schema": "notebooks"},)

    document_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("notebooks.documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    language: Mapped[str] = mapped_column(String(8), primary_key=True)
    guide: Mapped[dict[str, Any]] = mapped_column(JSONB)
