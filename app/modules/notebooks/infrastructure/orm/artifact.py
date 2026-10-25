"""ORM model of notebooks.artifacts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.enums import ArtifactKind, ArtifactStatus
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Artifact(IdMixin, TimestampMixin, Base):
    """A Studio output of a notebook (report, mind map, quiz, ...)."""

    __tablename__ = "artifacts"
    __table_args__ = (
        Index(
            "ix_artifacts_notebook_id_created_at",
            "notebook_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_artifacts_status",
            "status",
            postgresql_where=text("status IN ('queued', 'generating')"),
        ),
        Index("ix_artifacts_owner_id_created_at", "owner_id", "created_at"),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE")
    )
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    # The staff member who asked for it in a course workspace (None: the owner).
    requested_by: Mapped[UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(str_enum(ArtifactKind, "kind"))
    format: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        str_enum(ArtifactStatus, "status"), server_default=text("'queued'")
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    prompt: Mapped[str | None] = mapped_column(Text)
    source_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    source_map: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    sampled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    refs_index: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(100))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    weighted: Mapped[int | None] = mapped_column(Integer)
    cost_micro: Mapped[int | None] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    progress: Mapped[int | None] = mapped_column(SmallInteger)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid)
    flashcard_set_id: Mapped[UUID | None] = mapped_column(Uuid)
    cache_key: Mapped[str | None] = mapped_column(CHAR(64))  # shared Studio cache
    from_cache: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
