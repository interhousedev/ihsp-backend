"""SQL storage of the calendar feeds, the reminder ledger and exam dates."""

import datetime as dt
from uuid import UUID

from app.modules.admission.domain.calendar import CalendarFeed, ExamDate
from app.modules.admission.infrastructure.orm.applications import (
    ChecklistItemRow,
    ListEntryRow,
)
from app.modules.admission.infrastructure.orm.calendar import (
    CalendarFeedRow,
    CalendarReminderRow,
    ExamDateRow,
)
from app.modules.admission.infrastructure.orm.profile import ProfileRow

from sqlalchemy import delete, select, union, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _feed(row: CalendarFeedRow) -> CalendarFeed:
    offsets = row.alarm_offsets
    return CalendarFeed(
        id=row.id,
        user_id=row.user_id,
        token_hash=row.token_hash,
        locale=row.locale,
        alarm_offsets=tuple(int(o) for o in offsets) if offsets else None,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def _exam(row: ExamDateRow) -> ExamDate:
    return ExamDate(
        id=row.id,
        exam=row.exam,
        test_date=row.test_date,
        registration_deadline=row.registration_deadline,
        source_url=row.source_url,
    )


class SqlCalendarStore:
    """Each call opens and commits its own session."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self._sm = sessionmaker

    async def active_feed(self, user_id: UUID) -> CalendarFeed | None:
        """The user's live feed, if any."""
        async with self._sm() as session:
            row = await session.scalar(
                select(CalendarFeedRow)
                .where(
                    CalendarFeedRow.user_id == user_id,
                    CalendarFeedRow.revoked_at.is_(None),
                )
                .order_by(CalendarFeedRow.created_at.desc())
                .limit(1)
            )
        return _feed(row) if row is not None else None

    async def feed_by_hash(self, token_hash: str) -> CalendarFeed | None:
        """The live feed with this token hash, if any."""
        async with self._sm() as session:
            row = await session.scalar(
                select(CalendarFeedRow).where(
                    CalendarFeedRow.token_hash == token_hash,
                    CalendarFeedRow.revoked_at.is_(None),
                )
            )
        return _feed(row) if row is not None else None

    async def replace_feed(self, feed: CalendarFeed, now: dt.datetime) -> None:
        """Revoke the user's live feeds and add this one, in one transaction."""
        async with self._sm() as session, session.begin():
            await session.execute(
                update(CalendarFeedRow)
                .where(
                    CalendarFeedRow.user_id == feed.user_id,
                    CalendarFeedRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            session.add(
                CalendarFeedRow(
                    id=feed.id,
                    user_id=feed.user_id,
                    token_hash=feed.token_hash,
                    locale=feed.locale,
                    alarm_offsets=(
                        list(feed.alarm_offsets) if feed.alarm_offsets else None
                    ),
                    created_at=feed.created_at,
                )
            )

    async def revoke_feeds(self, user_id: UUID, now: dt.datetime) -> bool:
        """Revoke the user's live feeds; False when there was none."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                update(CalendarFeedRow)
                .where(
                    CalendarFeedRow.user_id == user_id,
                    CalendarFeedRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
        return bool(getattr(result, "rowcount", 0))

    async def set_alarms(self, user_id: UUID, offsets: tuple[int, ...]) -> bool:
        """Set the alarm offsets of the live feed; False when there is none."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                update(CalendarFeedRow)
                .where(
                    CalendarFeedRow.user_id == user_id,
                    CalendarFeedRow.revoked_at.is_(None),
                )
                .values(alarm_offsets=list(offsets) if offsets else None)
            )
        return bool(getattr(result, "rowcount", 0))

    async def claim_reminder(
        self, dedupe_key: str, user_id: UUID, now: dt.datetime
    ) -> bool:
        """Insert the ledger row; False when the key was already there."""
        async with self._sm() as session, session.begin():
            key = await session.scalar(
                insert(CalendarReminderRow)
                .values(dedupe_key=dedupe_key, user_id=user_id, sent_at=now)
                .on_conflict_do_nothing(index_elements=["dedupe_key"])
                .returning(CalendarReminderRow.dedupe_key)
            )
        return key is not None

    async def exam_dates(self) -> list[ExamDate]:
        """All exam dates, earliest first."""
        async with self._sm() as session:
            rows = await session.scalars(
                select(ExamDateRow).order_by(ExamDateRow.test_date, ExamDateRow.exam)
            )
            return [_exam(r) for r in rows]

    async def add_exam_date(self, exam: ExamDate) -> None:
        """Store an exam date."""
        async with self._sm() as session, session.begin():
            session.add(
                ExamDateRow(
                    id=exam.id,
                    exam=exam.exam,
                    test_date=exam.test_date,
                    registration_deadline=exam.registration_deadline,
                    source_url=exam.source_url,
                )
            )

    async def delete_exam_date(self, exam_id: UUID) -> bool:
        """Delete an exam date; False when unknown."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                delete(ExamDateRow).where(ExamDateRow.id == exam_id)
            )
        return bool(getattr(result, "rowcount", 0))

    async def admission_students(self) -> list[UUID]:
        """Students with a list, a checklist or a profile."""
        async with self._sm() as session:
            ids = await session.scalars(
                union(
                    select(ListEntryRow.student_id),
                    select(ChecklistItemRow.student_id),
                    select(ProfileRow.student_id),
                )
            )
            return list(ids)
