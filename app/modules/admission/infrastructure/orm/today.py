"""The Today feed: days a student worked and the season they picked."""

import datetime as dt
from uuid import UUID

from app.modules.admission.domain.today import SEASONS
from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base

from sqlalchemy import Date, DateTime, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

__all__ = [
    "ActivityDayRow",
    "ProgramsSeenRow",
    "SeasonOverrideRow",
    "StaffPinRow",
    "TodaySnoozeRow",
]


class ActivityDayRow(CreatedMixin, UpdatedMixin, Base):
    """A day on which the student changed something (the streak)."""

    __tablename__ = "activity_days"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)


class SeasonOverrideRow(CreatedMixin, UpdatedMixin, Base):
    """The season a student or counselor fixed instead of the automatic one."""

    __tablename__ = "season_overrides"
    __table_args__ = (check_in("key", SEASONS), S)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(10))


class TodaySnoozeRow(CreatedMixin, UpdatedMixin, Base):
    """A next action the student pushed back: hidden until `until`."""

    __tablename__ = "today_snoozes"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    count: Mapped[int] = mapped_column(SmallInteger)
    until: Mapped[dt.date] = mapped_column(Date)


class StaffPinRow(CreatedMixin, UpdatedMixin, Base):
    """The action a counselor pinned to the top of a student's Today."""

    __tablename__ = "staff_pins"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    href: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(String(500))
    pinned_by: Mapped[UUID] = mapped_column(Uuid)
    pinned_by_name: Mapped[str] = mapped_column(String(160))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class ProgramsSeenRow(CreatedMixin, UpdatedMixin, Base):
    """When the student last opened the new-programs block on Today."""

    __tablename__ = "today_programs_seen"
    __table_args__ = (S,)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
