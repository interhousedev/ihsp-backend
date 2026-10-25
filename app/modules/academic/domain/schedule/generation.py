"""Expanding timetable entries into dated lessons, and planning regeneration (ACA-7).

Everything here is pure: the use case loads entries and existing lessons, calls
``plan_generation`` and applies the result.
"""

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.domain.schedule.calendar import (
    bell_for,
    effective_weekday,
    lesson_times,
    week_parity,
)
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.ids import new_id


@dataclass(frozen=True, slots=True)
class PlannedLesson:
    """A lesson an entry produces on a date."""

    entry_id: UUID
    origin_date: dt.date
    term_id: UUID
    period: int
    starts_at: dt.datetime
    ends_at: dt.datetime
    subject_id: UUID
    teacher_id: UUID | None
    room_id: UUID | None
    audience: tuple[str, ...]

    @property
    def key(self) -> tuple[UUID, dt.date]:
        """Identity of the lesson: its entry and the date it was generated for."""
        return self.entry_id, self.origin_date


@dataclass(slots=True)
class Expansion:
    """Lessons produced for a date range, and entries skipped for lack of a bell."""

    planned: dict[tuple[UUID, dt.date], PlannedLesson] = field(default_factory=dict)
    missing_bells: set[UUID] = field(default_factory=set)


def expand_entries(
    term: Term, entries: Sequence[TimetableEntry], start: dt.date, end: dt.date
) -> Expansion:
    """Expand entries for each date in [start, end] that lies inside the term."""
    result = Expansion()
    first = max(start, term.starts_on)
    last = min(end, term.ends_on)
    day = first
    while day <= last:
        _expand_day(term, entries, day, result)
        day += dt.timedelta(days=1)
    return result


def _expand_day(
    term: Term, entries: Sequence[TimetableEntry], day: dt.date, result: Expansion
) -> None:
    weekday = effective_weekday(day, term)
    if weekday is None:
        return
    parity = week_parity(day, term)
    for entry in entries:
        if entry.weekday != weekday or not entry.valid_on(day):
            continue
        if entry.week_parity not in ("every", parity):
            continue
        bell = bell_for(term, entry.period, weekday)
        if bell is None:
            result.missing_bells.add(entry.id)
            continue
        starts_at, ends_at = lesson_times(day, bell[0], bell[1])
        planned = PlannedLesson(
            entry_id=entry.id,
            origin_date=day,
            term_id=term.id,
            period=entry.period,
            starts_at=starts_at,
            ends_at=ends_at,
            subject_id=entry.subject_id,
            teacher_id=entry.teacher_id,
            room_id=entry.room_id,
            audience=tuple(entry.audience),
        )
        result.planned[planned.key] = planned


@dataclass(slots=True)
class GenerationPlan:
    """What to write after comparing planned and existing lessons."""

    inserts: list[Lesson] = field(default_factory=list)
    updates: list[Lesson] = field(default_factory=list)
    cancels: list[Lesson] = field(default_factory=list)
    deletes: list[Lesson] = field(default_factory=list)
    missing_bells: set[UUID] = field(default_factory=set)

    @property
    def changed_ids(self) -> list[UUID]:
        """Ids of every lesson that was added, changed, cancelled or removed."""
        lessons: Iterable[Lesson] = (
            *self.inserts,
            *self.updates,
            *self.cancels,
            *self.deletes,
        )
        return [lesson.id for lesson in lessons]


def plan_generation(
    term: Term,
    entries: Sequence[TimetableEntry],
    existing: Sequence[Lesson],
    *,
    start: dt.date,
    end: dt.date,
    now: dt.datetime,
) -> GenerationPlan:
    """Compare what the entries produce with the generated lessons in the range."""
    expansion = expand_entries(term, entries, start, end)
    plan = GenerationPlan(missing_bells=expansion.missing_bells)
    seen: set[tuple[UUID, dt.date]] = set()
    for lesson in existing:
        if lesson.timetable_entry_id is None or lesson.origin_date is None:
            continue
        key = (lesson.timetable_entry_id, lesson.origin_date)
        seen.add(key)
        planned = expansion.planned.get(key)
        if planned is None:
            _plan_removal(plan, lesson, now)
        else:
            _plan_update(plan, lesson, planned, now)
    for key, planned in expansion.planned.items():
        if key not in seen:
            plan.inserts.append(_new_lesson(planned))
    return plan


def _new_lesson(planned: PlannedLesson) -> Lesson:
    return Lesson(
        id=new_id(),
        term_id=planned.term_id,
        date=planned.origin_date,
        period=planned.period,
        starts_at=planned.starts_at,
        ends_at=planned.ends_at,
        subject_id=planned.subject_id,
        teacher_id=planned.teacher_id,
        room_id=planned.room_id,
        audience=list(planned.audience),
        status="scheduled",
        is_overridden=False,
        timetable_entry_id=planned.entry_id,
        origin_date=planned.origin_date,
    )


def _plan_update(
    plan: GenerationPlan, lesson: Lesson, planned: PlannedLesson, now: dt.datetime
) -> None:
    if lesson.is_overridden or not lesson.starts_after(now):
        return
    changed = _apply_planned(lesson, planned)
    if lesson.status == "cancelled":
        lesson.status = "scheduled"
        changed = True
    if changed:
        plan.updates.append(lesson)


def _apply_planned(lesson: Lesson, planned: PlannedLesson) -> bool:
    new_values = {
        "period": planned.period,
        "starts_at": planned.starts_at,
        "ends_at": planned.ends_at,
        "subject_id": planned.subject_id,
        "teacher_id": planned.teacher_id,
        "room_id": planned.room_id,
        "audience": list(planned.audience),
    }
    changed = False
    for name, value in new_values.items():
        if getattr(lesson, name) != value:
            setattr(lesson, name, value)
            changed = True
    return changed


def _plan_removal(plan: GenerationPlan, lesson: Lesson, now: dt.datetime) -> None:
    if lesson.is_overridden or not lesson.starts_after(now):
        return
    if lesson.has_content:
        if lesson.status != "cancelled":
            lesson.status = "cancelled"
            plan.cancels.append(lesson)
    else:
        plan.deletes.append(lesson)
