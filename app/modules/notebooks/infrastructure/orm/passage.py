"""ORM model of notebooks.passages."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CHAR,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

SEARCH_VECTOR = "to_tsvector('russian', text) || to_tsvector('simple', text)"


class Passage(IdMixin, TimestampMixin, Base):
    """A chunk of a document: the unit of citation and of lexical retrieval.

    Passages belong to a document, so every source with the same text shares them.
    No GIN index: retrieval always filters one notebook (about 5 000 passages), so
    ranking on the fly is cheap and an index would be larger than the text.

    `content_hash` (sha256 of `text`) names the text itself: vectors computed for a
    passage are keyed by it, so equal passages of different documents share them.
    """

    __tablename__ = "passages"
    __table_args__ = (
        UniqueConstraint("document_id", "seq", name="uq_passages_document_id_seq"),
        Index("ix_passages_content_hash", "content_hash"),
        {"schema": "notebooks"},
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.documents.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(200))
    token_estimate: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True), deferred=True
    )
