"""Finding the term and times of a lesson on a date and period."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.ports.unit_of_work import (
    ScheduleUnitOfWork,
)
from app.modules.academic.domain.schedule.calendar import (
    bell_for,
    effective_weekday,
    lesson_times,
)
from app.modules.academic.domain.schedule.conflicts import (
    LessonSlot,
    lesson_conflicts,
)
from app.modules.academic.domain.schedule.errors import (
    GroupNotFoundError,
    NoBellError,
    NoTermForDateError,
    SubjectNotFoundError,
)
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Term
from app.shared.base_error import ConflictError


async def slot_times(
    uow: ScheduleUnitOfWork, day: dt.date, period: int
) -> tuple[Term, dt.datetime, dt.datetime]:
    """Return the term and UTC times for a period on a date, or raise."""
    term = await uow.terms.containing(day)
    if term is None:
        raise NoTermForDateError(params={"date": day.isoformat()})
    weekday = effective_weekday(day, term) or day.isoweekday()
    bell = bell_for(term, period, weekday)
    if bell is None:
        raise NoBellError(params={"period": period, "date": day.isoformat()})
    starts_at, ends_at = lesson_times(day, bell[0], bell[1])
    return term, starts_at, ends_at


async def check_subject_and_groups(
    uow: ScheduleUnitOfWork, subject_id: UUID, group_ids: set[UUID]
) -> Subject:
    """Return the subject, raising unless it and every group exist."""
    subject = await uow.subjects.get(subject_id)
    if subject is None:
        raise SubjectNotFoundError()
    missing = group_ids - set(await uow.groups.get_many(group_ids))
    if missing:
        raise GroupNotFoundError(params={"group_ids": sorted(str(g) for g in missing)})
    return subject


async def raise_on_lesson_conflicts(uow: ScheduleUnitOfWork, slot: LessonSlot) -> None:
    """Raise a ConflictError listing clashes with lessons at the same time."""
    others = await uow.lessons.find_overlapping(slot.starts_at, slot.ends_at)
    conflicts = lesson_conflicts(slot, others)
    if conflicts:
        raise ConflictError(params={"conflicts": [c.to_json() for c in conflicts]})
