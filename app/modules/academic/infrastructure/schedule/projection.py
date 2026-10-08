"""Lessons projected from timetable entries beyond the generation horizon."""

import datetime as dt
import uuid
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.domain.schedule.generation import expand_entries
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.infrastructure.orm import Lesson as LessonRow
from app.modules.academic.infrastructure.orm import Room as RoomRow
from app.modules.academic.infrastructure.orm import Subject as SubjectRow
from app.modules.academic.infrastructure.orm import Term as TermRow
from app.modules.academic.infrastructure.orm import TimetableEntry as EntryRow
from app.modules.academic.infrastructure.schedule.array_ops import overlaps
from app.modules.academic.infrastructure.schedule.lesson_views import (
    group_names_for,
    projected_view,
)
from app.modules.academic.infrastructure.schedule.mappers import (
    entry_to_entity,
    term_to_entity,
)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def projected_id(entry_id: UUID, day: dt.date) -> UUID:
    """Return the stable id of a projected lesson: uuid5(entry_id:date)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{entry_id}:{day.isoformat()}")


async def _last_generated(session: AsyncSession, term: Term) -> dt.date | None:
    stmt = select(func.max(LessonRow.date)).where(
        LessonRow.term_id == term.id, LessonRow.timetable_entry_id.is_not(None)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def projected_views(
    session: AsyncSession,
    keys: Sequence[str],
    start: dt.date,
    end: dt.date,
    locale: str,
) -> list[LessonView]:
    """Project lessons for audience keys on dates after the last generated lesson."""
    term_rows = await session.scalars(
        select(TermRow).where(TermRow.starts_on <= end, TermRow.ends_on >= start)
    )
    views: list[LessonView] = []
    for term_row in term_rows:
        term = term_to_entity(term_row)
        last = await _last_generated(session, term)
        first = max(start, last + dt.timedelta(days=1)) if last else start
        if first > min(end, term.ends_on):
            continue
        views.extend(await _project_term(session, term, keys, first, end, locale))
    return views


async def _project_term(
    session: AsyncSession,
    term: Term,
    keys: Sequence[str],
    first: dt.date,
    end: dt.date,
    locale: str,
) -> list[LessonView]:
    rows = await session.scalars(
        select(EntryRow).where(
            EntryRow.term_id == term.id, overlaps(EntryRow.audience, keys)
        )
    )
    entries = [entry_to_entity(row) for row in rows]
    planned = expand_entries(term, entries, first, end).planned
    if not planned:
        return []
    subjects = {
        row.id: row
        for row in await session.scalars(
            select(SubjectRow).where(
                SubjectRow.id.in_({p.subject_id for p in planned.values()})
            )
        )
    }
    room_ids = {p.room_id for p in planned.values() if p.room_id}
    rooms = {
        row.id: row
        for row in await session.scalars(
            select(RoomRow).where(RoomRow.id.in_(room_ids))
        )
    }
    names = await group_names_for(session, (p.audience for p in planned.values()))
    return [
        projected_view(
            item,
            lesson_id=projected_id(item.entry_id, item.origin_date),
            day=item.origin_date,
            subject=subjects[item.subject_id],
            room=rooms.get(item.room_id) if item.room_id else None,
            names=names,
            locale=locale,
        )
        for item in sorted(planned.values(), key=lambda p: p.starts_at)
    ]
