"""ORM model of lms.course_steps."""

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
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CourseStep(IdMixin, TimestampMixin, Base):
    """Stable identity of a step across versions, plus its working copy."""

    __tablename__ = "course_steps"
    __table_args__ = (
        Index("ix_course_steps_course_id", "course_id"),
        Index("ix_course_steps_file_ids", "file_ids", postgresql_using="gin"),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("lms.courses.id"))
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_hash: Mapped[str] = mapped_column(String(64))
    draft_updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    draft_updated_via: Mapped[str] = mapped_column(
        Enum(
            "ui",
            "mcp",
            name="draft_updated_via",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'ui'"),
    )
    file_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    lock_version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Circular with step_revisions.step_id, so the constraint is added with ALTER.
    live_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "lms.step_revisions.id",
            use_alter=True,
            name="fk_course_steps_live_revision_id_step_revisions",
        ),
    )
    live_hash: Mapped[str | None] = mapped_column(String(64))
    created_via: Mapped[str] = mapped_column(
        Enum(
            "ui",
            "mcp",
            name="created_via",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'ui'"),
    )
