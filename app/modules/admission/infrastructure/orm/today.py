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

from sqlalchemy import Date, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["ActivityDayRow", "SeasonOverrideRow"]


class ActivityDayRow(CreatedMixin, Base):
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
