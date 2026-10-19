"""ORM model of knowledge.entries."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import CHAR, Computed, Index, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

SEARCH_VECTOR = (
    "to_tsvector('simple', key || ' ' || coalesce(title, '') || ' ' || value)"
)


class KnowledgeEntryRow(IdMixin, TimestampMixin, Base):
    """A knowledge entry; `key` is lower case. Trigram and full-text GIN indexes."""

    __tablename__ = "entries"
    __table_args__ = (
        Index(
            "ix_entries_key_trgm",
            "key",
            postgresql_using="gin",
            postgresql_ops={"key": "gin_trgm_ops"},
        ),
        Index(
            "ix_entries_value_trgm",
            "value",
            postgresql_using="gin",
            postgresql_ops={"value": "gin_trgm_ops"},
        ),
        Index("ix_entries_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_entries_updated_at", "updated_at"),
        {"schema": "knowledge"},
    )

    key: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str | None] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), server_default=text("'{}'")
    )
    author_id: Mapped[UUID] = mapped_column(Uuid)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed(SEARCH_VECTOR, persisted=True), deferred=True
    )
