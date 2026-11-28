"""ORM models of course badges, their awards and the course badge settings."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Badge(IdMixin, TimestampMixin, Base):
    """A badge of a course: its design and the rule that awards it."""

    __tablename__ = "badges"
    __table_args__ = (
        CheckConstraint(
            "shape IN ('circle', 'shield', 'hexagon', 'star')", name="shape"
        ),
        CheckConstraint("color ~ '^#[0-9a-f]{6}$'", name="color"),
        CheckConstraint(
            "(scope = 'course' AND course_id IS NOT NULL) "
            "OR (scope = 'platform' AND course_id IS NULL)",
            name="scope_course",
        ),
        Index("ix_badges_course_id", "course_id"),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    scope: Mapped[str] = mapped_column(String(16), server_default=text("'course'"))
    template_code: Mapped[str | None] = mapped_column(String(32))
    template_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    name: Mapped[dict[str, Any]] = mapped_column(JSONB)
    description: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    icon: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(7))
    shape: Mapped[str] = mapped_column(String(16))
    image_file_id: Mapped[UUID | None] = mapped_column(Uuid)
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)


class BadgeAward(IdMixin, TimestampMixin, Base):
    """A badge a learner earned; one row per badge and learner (idempotent)."""

    __tablename__ = "badge_awards"
    __table_args__ = (
        UniqueConstraint("badge_id", "user_id", name="uq_badge_awards_badge_user"),
        Index("ix_badge_awards_user_id_course_id", "user_id", "course_id"),
        {"schema": "lms"},
    )

    badge_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.badges.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(Uuid)
    course_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BadgeSettings(TimestampMixin, Base):
    """Per course: whether learners see the badges they have not earned yet."""

    __tablename__ = "badge_settings"
    __table_args__ = ({"schema": "lms"},)

    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE"), primary_key=True
    )
    show_locked: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
