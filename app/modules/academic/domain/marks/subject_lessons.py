"""The student's lesson list of one subject, built around the current moment."""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain.marks.attendance import attendance_state
from app.modules.academic.domain.marks.read_models import LessonRow, MarkRow

UPCOMING_DAYS = 14
PAST_PAGE = 10

_TYPE_ORDER = {"lesson": 0, "midterm": 1, "final": 2}


@dataclass(frozen=True, slots=True)
class LessonMarkValue:
    """One mark placed on a lesson of the list."""

    type: str
    value: int


@dataclass(frozen=True, slots=True)
class SubjectLessonView:
    """One row of the subject hub list."""

    lesson_id: UUID
    date: dt.date
    starts_at: dt.datetime
    kind: str
    topic: str | None
    marks: tuple[LessonMarkValue, ...]
    attendance: str | None
    materials_count: int
    past: bool


@dataclass(frozen=True, slots=True)
class SubjectLessonPage:
    """The visible slice: newest past lessons first, then the upcoming ones."""

    items: tuple[SubjectLessonView, ...]
    has_more_past: bool


def _attendance(student_id: UUID, lesson: LessonRow) -> str | None:
    state = attendance_state(
        student_id,
        lesson.attendance_roster,
        lesson.attendance_absent,
        lesson.attendance_excused,
        lesson.attendance_late,
    )
    if state in ("present", "late"):
        return state
    if state in ("absent", "excused"):
        return "absent"
    return None


def lesson_marks(
    lessons: Sequence[LessonRow], marks: Sequence[MarkRow]
) -> dict[UUID, tuple[LessonMarkValue, ...]]:
    """Place each mark on a lesson: by lesson id, else on the first lesson of its date.

    A mark gets its lesson id only when it is synced, so a mark synced before its lesson
    was in the timetable has none. Such a mark goes to the earliest scheduled lesson of
    the subject on its date, the rule the sync uses for a new mark. Marks linked to a
    lesson outside `lessons` are left out.
    """
    lesson_ids = {x.id for x in lessons}
    first_on_day: dict[dt.date, UUID] = {}
    for lesson in sorted(lessons, key=lambda x: (x.date, x.period, x.starts_at)):
        if lesson.status == "scheduled":
            first_on_day.setdefault(lesson.date, lesson.id)
    placed: dict[UUID, list[MarkRow]] = {}
    for mark in marks:
        if mark.lesson_id is not None:
            target = mark.lesson_id if mark.lesson_id in lesson_ids else None
        else:
            target = first_on_day.get(mark.date)
        if target is not None:
            placed.setdefault(target, []).append(mark)
    return {
        lesson_id: tuple(
            LessonMarkValue(type=m.type, value=m.value)
            for m in sorted(
                group,
                key=lambda m: (_TYPE_ORDER.get(m.type, len(_TYPE_ORDER)), m.ordinal),
            )
        )
        for lesson_id, group in placed.items()
    }


def build_subject_lessons(
    lessons: Sequence[LessonRow],
    *,
    student_id: UUID,
    now: dt.datetime,
    marks: Sequence[MarkRow],
    materials: Mapping[UUID, int],
    past_limit: int = PAST_PAGE,
    past_offset: int = 0,
    upcoming_days: int = UPCOMING_DAYS,
) -> SubjectLessonPage:
    """Split the lessons by `now`; attendance and marks show only for the past."""
    horizon = now + dt.timedelta(days=upcoming_days)
    past = sorted(
        (x for x in lessons if x.starts_at < now),
        key=lambda x: x.starts_at,
        reverse=True,
    )
    upcoming = sorted(
        (x for x in lessons if now <= x.starts_at <= horizon), key=lambda x: x.starts_at
    )
    shown_past = past[past_offset : past_offset + past_limit]
    placed = lesson_marks(lessons, marks)

    def view(lesson: LessonRow, is_past: bool) -> SubjectLessonView:
        return SubjectLessonView(
            lesson_id=lesson.id,
            date=lesson.date,
            starts_at=lesson.starts_at,
            kind=lesson.kind,
            topic=lesson.topic,
            marks=placed.get(lesson.id, ()) if is_past else (),
            attendance=_attendance(student_id, lesson) if is_past else None,
            materials_count=materials.get(lesson.id, 0),
            past=is_past,
        )

    items = [view(x, True) for x in shown_past]
    if past_offset == 0:
        items += [view(x, False) for x in upcoming]
    return SubjectLessonPage(
        items=tuple(items), has_more_past=len(past) > past_offset + past_limit
    )


def lesson_results(
    lessons: Sequence[LessonRow],
    *,
    student_id: UUID,
    now: dt.datetime,
    marks: Mapping[UUID, int],
) -> list[tuple[UUID, str | None, int | None]]:
    """Return (lesson id, attendance, mark) for the lessons that started before `now`.

    A lesson that has not started has no result, so the calendar shows no dot.
    """
    return [
        (x.id, _attendance(student_id, x), marks.get(x.id))
        for x in lessons
        if x.starts_at < now
    ]
