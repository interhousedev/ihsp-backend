"""ORM model of lms.courses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Course(IdMixin, TimestampMixin, Base):
    """A course with its live values and its working copy (draft)."""

    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_courses_slug"),
        Index(
            "ix_courses_invite_code",
            "invite_code",
            unique=True,
            postgresql_where=text("invite_code IS NOT NULL"),
        ),
        {"schema": "lms"},
    )

    slug: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    cover_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    visibility: Mapped[str] = mapped_column(
        Enum(
            "public",
            "invite",
            name="visibility",
            native_enum=False,
            create_constraint=True,
        )
    )
    invite_code: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        Enum(
            "active",
            "archived",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'active'"),
    )
    created_by: Mapped[UUID] = mapped_column(Uuid)
    draft_meta: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_outline: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("""'{"sections": []}'::jsonb""")
    )
    draft_updated_by: Mapped[UUID | None] = mapped_column(Uuid)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    draft_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    outline_hash: Mapped[str] = mapped_column(String(64))
    live_outline_hash: Mapped[str | None] = mapped_column(String(64))
    # Circular with course_versions.course_id, so the constraint is added with ALTER.
    live_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "lms.course_versions.id",
            use_alter=True,
            name="fk_courses_live_version_id_course_versions",
        ),
    )
