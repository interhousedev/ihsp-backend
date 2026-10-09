"""ORM model of notebooks.sources."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.enums import GuideStatus, SourceKind, SourceStatus
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Source(IdMixin, TimestampMixin, Base):
    """One text a notebook is grounded in (file, chat, lesson, note, ...)."""

    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_notebook_id_position", "notebook_id", "position"),
        Index(
            "uq_sources_notebook_id_ref_key",
            "notebook_id",
            "ref_key",
            unique=True,
            postgresql_where=text("ref_key IS NOT NULL"),
        ),
        Index(
            "ix_sources_ref_key",
            "ref_key",
            postgresql_where=text("ref_key IS NOT NULL"),
        ),
        Index("ix_sources_owner_id", "owner_id"),
        Index(
            "ix_sources_document_id",
            "document_id",
            postgresql_where=text("document_id IS NOT NULL"),
        ),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE")
    )
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(str_enum(SourceKind, "kind"))
    ref: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    ref_key: Mapped[str | None] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(String(255))
    origin: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    position: Mapped[int] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    status: Mapped[str] = mapped_column(
        str_enum(SourceStatus, "status"), server_default=text("'pending'")
    )
    failure: Mapped[str | None] = mapped_column(String(32))
    body_md: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64))
    # The shared text and passages; RESTRICT so a document in use is never deleted.
    document_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("notebooks.documents.id", ondelete="RESTRICT")
    )
    upstream_version: Mapped[str | None] = mapped_column(String(64))
    word_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    char_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    token_estimate: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    passage_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    guide: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    guide_status: Mapped[str] = mapped_column(
        str_enum(GuideStatus, "guide_status"), server_default=text("'none'")
    )
    text_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
