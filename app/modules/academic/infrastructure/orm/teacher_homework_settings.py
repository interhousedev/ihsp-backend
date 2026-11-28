"""ORM model of academic.teacher_homework_settings."""

from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import Boolean, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class TeacherHomeworkSettings(TimestampMixin, Base):
    """A teacher's homework defaults: accept submissions, tell about new ones."""

    __tablename__ = "teacher_homework_settings"
    __table_args__ = ({"schema": "academic"},)

    teacher_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    accept_by_default: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false")
    )
    notify_on_submission: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true")
    )
