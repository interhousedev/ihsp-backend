"""ORM model of lms.enrollments."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Enrollment(IdMixin, TimestampMixin, Base):
    """A user's enrollment in a course with progress on the live version."""

    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_enrollments_course_user"),
        CheckConstraint("progress_pct BETWEEN 0 AND 100", name="progress_pct"),
        Index("ix_enrollments_user_id", "user_id"),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("lms.courses.id"))
    user_id: Mapped[UUID] = mapped_column(Uuid)
    via: Mapped[str] = mapped_column(
        Enum(
            "self",
            "invite",
            name="via",
            native_enum=False,
            create_constraint=True,
        )
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_pct: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    progress_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("lms.course_versions.id")
    )
    last_seen_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("lms.course_versions.id")
    )
