"""The student's lesson list of one subject, built around the current moment."""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain.marks.attendance import attendance_state
from app.modules.academic.domain.marks.read_models import LessonRow

UPCOMING_DAYS = 14
PAST_PAGE = 10


@dataclass(frozen=True, slots=True)
class SubjectLessonView:
    """One row of the subject hub list."""

    lesson_id: UUID
    date: dt.date
    starts_at: dt.datetime
    kind: str
    topic: str | None
    mark: int | None
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
    )
    if state == "present":
        return "present"
    if state in ("absent", "excused"):
        return "absent"
    return None


def build_subject_lessons(
    lessons: Sequence[LessonRow],
    *,
    student_id: UUID,
    now: dt.datetime,
    marks: Mapping[UUID, int],
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

    def view(lesson: LessonRow, is_past: bool) -> SubjectLessonView:
        return SubjectLessonView(
            lesson_id=lesson.id,
            date=lesson.date,
            starts_at=lesson.starts_at,
            kind=lesson.kind,
            topic=lesson.topic,
            mark=marks.get(lesson.id) if is_past else None,
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
