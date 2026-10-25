"""ORM model of lms.course_versions."""

from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CourseVersion(IdMixin, TimestampMixin, Base):
    """Immutable manifest of a published course."""

    __tablename__ = "course_versions"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "number", name="uq_course_versions_course_number"
        ),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("lms.courses.id"))
    number: Mapped[int] = mapped_column(Integer)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outline: Mapped[dict[str, Any]] = mapped_column(JSONB)
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(1000))
    published_by: Mapped[UUID] = mapped_column(Uuid)
