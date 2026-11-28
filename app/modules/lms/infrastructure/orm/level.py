"""ORM models of level schemes and the learners' high-water marks."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class LevelScheme(IdMixin, TimestampMixin, Base):
    """A level curve with its tiers, for the platform or one course."""

    __tablename__ = "level_schemes"
    __table_args__ = (
        CheckConstraint("scope IN ('platform', 'course')", name="scope"),
        CheckConstraint(
            "(scope = 'course') = (course_id IS NOT NULL)", name="scope_course"
        ),
        Index(
            "uq_level_schemes_active_platform",
            "scope",
            unique=True,
            postgresql_where=text("active AND scope = 'platform'"),
        ),
        Index(
            "uq_level_schemes_active_course",
            "course_id",
            unique=True,
            postgresql_where=text("active AND scope = 'course'"),
        ),
        {"schema": "lms"},
    )

    scope: Mapped[str] = mapped_column(String(16))
    course_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    name: Mapped[dict[str, Any]] = mapped_column(JSONB)
    curve: Mapped[dict[str, Any]] = mapped_column(JSONB)
    tiers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class LevelMark(IdMixin, TimestampMixin, Base):
    """The highest level shown to a learner on the platform or in a course."""

    __tablename__ = "level_marks"
    __table_args__ = (
        Index(
            "uq_level_marks_user_platform",
            "user_id",
            unique=True,
            postgresql_where=text("course_id IS NULL"),
        ),
        Index(
            "uq_level_marks_user_course",
            "user_id",
            "course_id",
            unique=True,
            postgresql_where=text("course_id IS NOT NULL"),
        ),
        {"schema": "lms"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    course_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    level: Mapped[int] = mapped_column(Integer, server_default=text("1"))
