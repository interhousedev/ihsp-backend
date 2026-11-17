"""FAQ knowledge-base articles of the admission app."""

from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Computed, Index, String, Text, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

KB_SEARCH_SQL = "to_tsvector('simple'::regconfig, (title || ' '::text) || body)"


class KbArticleRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One article in one language; `search` is a generated full-text vector."""

    __tablename__ = "kb_articles"
    __table_args__ = (
        check_in("status", ("draft", "published")),
        check_in("locale", ("uz", "ru", "en")),
        Index("ix_admission_kb_articles_search", "search", postgresql_using="gin"),
        S,
    )

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(2))
    status: Mapped[str] = mapped_column(String(9), index=True)
    tags: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql_text("'[]'::jsonb")
    )
    author_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed(KB_SEARCH_SQL, persisted=True)
    )
