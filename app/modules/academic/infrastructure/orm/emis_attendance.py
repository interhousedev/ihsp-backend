"""ORM model of academic.emis_attendance."""

import datetime as dt
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import Date, DateTime, ForeignKey, Integer, SmallInteger, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column


class EmisAttendance(TimestampMixin, Base):
    """Attendance EMIS reported for one student, subject and semester.

    ``absent_dates`` is None when EMIS sent no per-lesson flags; ``absence_total`` is
    None when it sent no subject total. A row exists only if EMIS sent either.
    """

    __tablename__ = "emis_attendance"
    __table_args__ = ({"schema": "academic"},)

    student_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("academic.students.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("academic.subjects.id", ondelete="CASCADE"), primary_key=True
    )
    semester: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    absent_dates: Mapped[list[dt.date] | None] = mapped_column(ARRAY(Date))
    absence_total: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
