"""ORM model of lms.access_rules."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AccessRule(TimestampMixin, Base):
    """The audience of a course (target = course id) or of one of its steps."""

    __tablename__ = "access_rules"
    __table_args__ = (
        CheckConstraint(
            "audience IN ('public', 'signed_in', 'students', 'chosen')",
            name="audience",
        ),
        CheckConstraint("when_denied IN ('hidden', 'locked')", name="when_denied"),
        Index("ix_access_rules_course_id", "course_id"),
        {"schema": "lms"},
    )

    target_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    audience: Mapped[str] = mapped_column(String(16), server_default=text("'public'"))
    when_denied: Mapped[str] = mapped_column(
        String(16), server_default=text("'hidden'")
    )
    group_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    user_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'"))
    updated_by: Mapped[UUID | None] = mapped_column(Uuid)
