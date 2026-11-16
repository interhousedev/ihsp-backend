"""In-memory CalendarStore for the unit tests."""

import dataclasses
import datetime as dt
from uuid import UUID

from app.modules.admission.domain.calendar import CalendarFeed, ExamDate


class FakeCalendarStore:
    """Feeds, the reminder ledger and exam dates in dictionaries."""

    def __init__(self, students: list[UUID] | None = None) -> None:
        """Start empty; `students` is what the reminder job visits."""
        self.feeds: list[CalendarFeed] = []
        self.claimed: set[str] = set()
        self.exams: dict[UUID, ExamDate] = {}
        self.students = list(students or [])

    async def active_feed(self, user_id: UUID) -> CalendarFeed | None:
        return next(
            (f for f in self.feeds if f.user_id == user_id and f.revoked_at is None),
            None,
        )

    async def feed_by_hash(self, token_hash: str) -> CalendarFeed | None:
        return next(
            (
                f
                for f in self.feeds
                if f.token_hash == token_hash and f.revoked_at is None
            ),
            None,
        )

    async def replace_feed(self, feed: CalendarFeed, now: dt.datetime) -> None:
        await self.revoke_feeds(feed.user_id, now)
        self.feeds.append(feed)

    async def revoke_feeds(self, user_id: UUID, now: dt.datetime) -> bool:
        hit = False
        for i, f in enumerate(self.feeds):
            if f.user_id == user_id and f.revoked_at is None:
                self.feeds[i] = dataclasses.replace(f, revoked_at=now)
                hit = True
        return hit

    async def set_alarms(self, user_id: UUID, offsets: tuple[int, ...]) -> bool:
        for i, f in enumerate(self.feeds):
            if f.user_id == user_id and f.revoked_at is None:
                self.feeds[i] = dataclasses.replace(f, alarm_offsets=offsets or None)
                return True
        return False

    async def claim_reminder(
        self, dedupe_key: str, user_id: UUID, now: dt.datetime
    ) -> bool:
        if dedupe_key in self.claimed:
            return False
        self.claimed.add(dedupe_key)
        return True

    async def exam_dates(self) -> list[ExamDate]:
        return sorted(self.exams.values(), key=lambda e: e.test_date)

    async def add_exam_date(self, exam: ExamDate) -> None:
        self.exams[exam.id] = exam

    async def delete_exam_date(self, exam_id: UUID) -> bool:
        return self.exams.pop(exam_id, None) is not None

    async def admission_students(self) -> list[UUID]:
        return list(self.students)
