"""ORM model of lms.course_staff."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class CourseStaff(IdMixin, TimestampMixin, Base):
    """A staff member of a course with a label and permissions."""

    __tablename__ = "course_staff"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_course_staff_course_user"),
        CheckConstraint(
            "permissions <@ ARRAY['edit', 'publish', 'review', 'manage_staff',"
            " 'view_drafts']::text[]",
            name="permissions",
        ),
        Index("ix_course_staff_user_id", "user_id"),
        {"schema": "lms"},
    )

    course_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("lms.courses.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(100))
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    show_on_page: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    added_by: Mapped[UUID] = mapped_column(Uuid)
