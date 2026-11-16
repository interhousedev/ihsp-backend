"""ORM of the deadline calendar: ICS feeds, the reminder ledger, exam dates."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Date, DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["CalendarFeedRow", "CalendarReminderRow", "ExamDateRow"]

EXAM_VALUES = ("ielts", "toefl", "duolingo", "sat", "act")


class CalendarFeedRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A private ICS feed; only the SHA-256 of its token is stored."""

    __tablename__ = "calendar_feeds"
    __table_args__ = (S,)

    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    locale: Mapped[str] = mapped_column(String(5))
    alarm_offsets: Mapped[list[Any] | None] = mapped_column(JSONB)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CalendarReminderRow(CreatedMixin, UpdatedMixin, Base):
    """Ledger of sent calendar reminders; the key makes each fire once."""

    __tablename__ = "calendar_reminders"
    __table_args__ = (S,)

    dedupe_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExamDateRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A test day of an exam and the last day to register for it."""

    __tablename__ = "exam_dates"
    __table_args__ = (check_in("exam", EXAM_VALUES), S)

    exam: Mapped[str] = mapped_column(String(10))
    test_date: Mapped[date] = mapped_column(Date)
    registration_deadline: Mapped[date] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(500))
