"""The deadline calendar: pluggable sources of dated entries and its store.

Any module adds entries to a student's calendar (the web view, the ICS feed and
the reminder job) by implementing `DeadlineSource` and registering it with
`CalendarService.register` at bootstrap.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.calendar import (
    CalendarEntry,
    CalendarFeed,
    CalendarSourceName,
    ExamDate,
)


class DeadlineSource(Protocol):
    """A provider of calendar entries (university, checklist, exams, opportunities)."""

    @property
    def name(self) -> CalendarSourceName:
        """The stable source identifier."""
        ...

    async def entries(
        self, student_id: UUID, start: dt.date, end: dt.date, locale: str
    ) -> list[CalendarEntry]:
        """Entries of the student whose `day` falls within [start, end]."""
        ...

    async def students(self) -> Sequence[UUID]:
        """Students that may have entries; the reminder job visits these."""
        ...


class CalendarStore(Protocol):
    """Feeds, the reminder ledger and exam dates."""

    async def active_feed(self, user_id: UUID) -> CalendarFeed | None:
        """The user's live feed, if any."""
        ...

    async def feed_by_hash(self, token_hash: str) -> CalendarFeed | None:
        """The live feed with this token hash, if any."""
        ...

    async def replace_feed(self, feed: CalendarFeed, now: dt.datetime) -> None:
        """Revoke the user's live feeds and add this one."""
        ...

    async def revoke_feeds(self, user_id: UUID, now: dt.datetime) -> bool:
        """Revoke the user's live feeds; False when there was none."""
        ...

    async def set_alarms(self, user_id: UUID, offsets: tuple[int, ...]) -> bool:
        """Set the alarm offsets of the live feed; False when there is none."""
        ...

    async def claim_reminder(
        self, dedupe_key: str, user_id: UUID, now: dt.datetime
    ) -> bool:
        """Record a reminder as sent; False when it already was."""
        ...

    async def exam_dates(self) -> list[ExamDate]:
        """All exam dates, earliest first."""
        ...

    async def add_exam_date(self, exam: ExamDate) -> None:
        """Store an exam date."""
        ...

    async def delete_exam_date(self, exam_id: UUID) -> bool:
        """Delete an exam date; False when unknown."""
        ...

    async def admission_students(self) -> list[UUID]:
        """Students with a list, a checklist or a profile."""
        ...
