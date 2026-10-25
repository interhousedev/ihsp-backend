"""ORM model of lms.step_revisions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class StepRevision(IdMixin, TimestampMixin, Base):
    """Immutable frozen content of a step (publish, checkpoint or preview)."""

    __tablename__ = "step_revisions"
    __table_args__ = (
        UniqueConstraint(
            "step_id", "content_hash", name="uq_step_revisions_step_content_hash"
        ),
        Index(
            "ix_step_revisions_step_id_kind_created_at",
            "step_id",
            "kind",
            "created_at",
        ),
        Index("ix_step_revisions_file_ids", "file_ids", postgresql_using="gin"),
        {"schema": "lms"},
    )

    step_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.course_steps.id", ondelete="RESTRICT")
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(
        Enum(
            "publish",
            "checkpoint",
            "preview",
            name="kind",
            native_enum=False,
            create_constraint=True,
        )
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    label: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[UUID] = mapped_column(Uuid)
