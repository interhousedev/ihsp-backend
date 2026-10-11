"""ORM models of the stored web pages and of the cached web queries (schema ``ai``).

A page is the text Exa returned for a URL, kept so that a later search can answer from
it. Its vector is in `vectors.embeddings` under `content_hash` (the shared kernel, as
for notebook passages), so equal texts are embedded once.
"""

from datetime import date, datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CHAR,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column


class WebPageRow(IdMixin, TimestampMixin, Base):
    """One web page the search found: its normalised URL is unique."""

    __tablename__ = "web_pages"
    __table_args__ = (
        UniqueConstraint("url", name="uq_web_pages_url"),
        Index("ix_web_pages_last_seen_at", "last_seen_at"),
        Index("ix_web_pages_content_hash", "content_hash"),
        {"schema": "ai"},
    )

    url: Mapped[str] = mapped_column(Text)
    site: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    highlight: Mapped[str] = mapped_column(Text, server_default=sql_text("''"))
    published_date: Mapped[date | None] = mapped_column(Date)
    content_hash: Mapped[str] = mapped_column(CHAR(64))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    times_returned: Mapped[int] = mapped_column(Integer, server_default=sql_text("1"))


class WebQueryRow(TimestampMixin, Base):
    """The ordered pages one query returned, kept for `query_cache_days`."""

    __tablename__ = "web_queries"
    __table_args__ = (
        Index("ix_web_queries_created_at", "created_at"),
        {"schema": "ai"},
    )

    cache_key: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    query: Mapped[str] = mapped_column(Text)
    page_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid))
