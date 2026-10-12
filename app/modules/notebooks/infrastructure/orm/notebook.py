"""ORM model of notebooks.notebooks."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.enums import NotebookOrigin, SummaryStatus
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# Subject and lesson notebooks (course workspaces and manual ones are not "auto").
AUTO_ORIGINS = "origin IN ('subject_auto', 'lesson_auto')"
AUTO_TARGET = (
    "(origin = 'manual' AND subject_id IS NULL AND lesson_id IS NULL "
    "AND auto_settings IS NULL AND course_id IS NULL) "
    "OR (origin = 'subject_auto' AND subject_id IS NOT NULL "
    "AND lesson_id IS NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin = 'lesson_auto' AND lesson_id IS NOT NULL "
    "AND subject_id IS NOT NULL AND auto_settings IS NOT NULL "
    "AND course_id IS NULL) "
    "OR (origin IN ('course', 'course_student') AND course_id IS NOT NULL "
    "AND subject_id IS NULL AND lesson_id IS NULL AND auto_settings IS NULL)"
)
CHAT_CONFIG_DEFAULT = (
    '{"style": "default", "custom_prompt": null, "length": "default", '
    '"language": "auto"}'
)


class Notebook(IdMixin, TimestampMixin, Base):
    """A student's collection of sources, or the shared workspace of an LMS course."""

    __tablename__ = "notebooks"
    __table_args__ = (
        Index(
            "ix_notebooks_owner_id_pinned_last_opened_at",
            "owner_id",
            text("pinned DESC"),
            text("last_opened_at DESC NULLS LAST"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_notebooks_summary_due_at",
            "summary_due_at",
            postgresql_where=text("summary_status = 'stale'"),
        ),
        # One live subject notebook per student and subject, one per lesson.
        Index(
            "ix_notebooks_owner_id_subject_id_auto",
            "owner_id",
            "subject_id",
            unique=True,
            postgresql_where=text(
                "origin = 'subject_auto' AND group_id IS NULL AND deleted_at IS NULL"
            ),
        ),
        # A teacher has one per subject and group they teach it to.
        Index(
            "ix_notebooks_owner_id_subject_id_group_id_auto",
            "owner_id",
            "subject_id",
            "group_id",
            unique=True,
            postgresql_where=text(
                "origin = 'subject_auto' AND group_id IS NOT NULL "
                "AND deleted_at IS NULL"
            ),
        ),
        Index(
            "ix_notebooks_owner_id_lesson_id_auto",
            "owner_id",
            "lesson_id",
            unique=True,
            postgresql_where=text("origin = 'lesson_auto' AND deleted_at IS NULL"),
        ),
        # The sweep and the fan-out of a changed lesson look auto notebooks up.
        Index(
            "ix_notebooks_subject_id_auto",
            "subject_id",
            postgresql_where=text(f"{AUTO_ORIGINS} AND deleted_at IS NULL"),
        ),
        Index(
            "ix_notebooks_lesson_id_auto",
            "lesson_id",
            postgresql_where=text("origin = 'lesson_auto' AND deleted_at IS NULL"),
        ),
        Index(
            "ix_notebooks_auto_synced_at",
            "auto_synced_at",
            postgresql_where=text(f"{AUTO_ORIGINS} AND deleted_at IS NULL"),
        ),
        # One live workspace per LMS course (get-or-create re-reads on a conflict).
        Index(
            "ix_notebooks_course_id_workspace",
            "course_id",
            unique=True,
            postgresql_where=text("origin = 'course' AND deleted_at IS NULL"),
        ),
        # One live course notebook per enrolled student and course.
        Index(
            "ix_notebooks_owner_id_course_id_student",
            "owner_id",
            "course_id",
            unique=True,
            postgresql_where=text("origin = 'course_student' AND deleted_at IS NULL"),
        ),
        # A new revision of a course finds the notebooks to bring up to date.
        Index(
            "ix_notebooks_course_id_student",
            "course_id",
            postgresql_where=text("origin = 'course_student' AND deleted_at IS NULL"),
        ),
        CheckConstraint(AUTO_TARGET, name="auto_target"),
        CheckConstraint(
            "group_id IS NULL OR origin = 'subject_auto'", name="group_subject_only"
        ),
        {"schema": "notebooks"},
    )

    owner_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(120))
    title_auto: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    emoji: Mapped[str | None] = mapped_column(String(16))
    emoji_auto: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    chat_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text(f"'{CHAT_CONFIG_DEFAULT}'::jsonb")
    )
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary_status: Mapped[str] = mapped_column(
        str_enum(SummaryStatus, "summary_status"), server_default=text("'none'")
    )
    summary_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_hash: Mapped[str | None] = mapped_column(String(64))
    source_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    char_count: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(
        str_enum(NotebookOrigin, "origin"), server_default=text("'manual'")
    )
    subject_id: Mapped[UUID | None] = mapped_column(Uuid)
    lesson_id: Mapped[UUID | None] = mapped_column(Uuid)
    # A teacher's subject notebook is scoped to one group (a student's has none).
    group_id: Mapped[UUID | None] = mapped_column(Uuid)
    # SQL NULL for a manual notebook (the CHECK constraint tests `IS NULL`).
    auto_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True)
    )
    auto_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    space_key: Mapped[str | None] = mapped_column(String(200))  # the shared space
    course_id: Mapped[UUID | None] = mapped_column(Uuid)  # a course workspace
