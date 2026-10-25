"""ORM model of notify.course_broadcasts."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin

from sqlalchemy import DateTime, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class CourseBroadcast(IdMixin, Base):
    """A message a course admin sent to the students enrolled in a course."""

    __tablename__ = "course_broadcasts"
    __table_args__ = (
        Index("ix_course_broadcasts_course_id_created_at", "course_id", "created_at"),
        {"schema": "notify"},
    )

    course_id: Mapped[UUID] = mapped_column(Uuid)
    author_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # NULL until the first edit; set (never cleared) by every edit.
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
