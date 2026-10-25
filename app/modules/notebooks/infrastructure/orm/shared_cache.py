"""ORM models of the shared caches: notebook summaries and Studio outputs."""

from datetime import datetime
from typing import Any

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import CHAR, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class SharedSummary(TimestampMixin, Base):
    """A notebook summary for a set of texts in one language (built once)."""

    __tablename__ = "shared_summaries"
    __table_args__ = ({"schema": "notebooks"},)

    selection_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    language: Mapped[str] = mapped_column(String(8), primary_key=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hits: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class SharedArtifact(TimestampMixin, Base):
    """A finished Studio output, served to everyone who asks for the same thing."""

    __tablename__ = "shared_artifacts"
    __table_args__ = ({"schema": "notebooks"},)

    cache_key: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    format: Mapped[str | None] = mapped_column(String(20))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    refs_index: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_map: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Which document each cited source was, to point a hit at the student's sources.
    source_documents: Mapped[dict[str, Any]] = mapped_column(JSONB)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sampled: Mapped[bool] = mapped_column(server_default=text("false"))
    model: Mapped[str | None] = mapped_column(String(100))
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hits: Mapped[int] = mapped_column(Integer, server_default=text("0"))
