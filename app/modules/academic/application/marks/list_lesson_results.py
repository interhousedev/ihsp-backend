"""Attendance and marks of past lessons in a date range (calendar dots)."""

import datetime as dt
from typing import Any

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.marks.errors import StudentNotFoundError
from app.modules.academic.domain.marks.subject_lessons import lesson_results
from app.shared.actor import Actor
from app.shared.clock import Clock

MAX_DAYS = 62


class ListLessonResults:
    """Builds `LessonResult` rows for the calendar."""

    def __init__(self, *, uow_factory: MarksUowFactory, clock: Clock) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, actor: Actor, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        """Return the result of every lesson that started before now."""
        end = min(end, start + dt.timedelta(days=MAX_DAYS))
        async with self._uow_factory() as uow:
            ctx = await uow.reader.student_context(actor.user_id)
            if ctx is None:
                raise StudentNotFoundError()
            lessons = await uow.reader.lessons(ctx, start=start, end=end)
            marks = await uow.reader.marks(actor.user_id, start=start, end=end)
        by_lesson = {m.lesson_id: m.value for m in marks if m.lesson_id is not None}
        rows = lesson_results(
            lessons, student_id=actor.user_id, now=self._clock.now(), marks=by_lesson
        )
        return [
            {"lesson_id": lid, "attendance": attendance, "mark": mark}
            for lid, attendance, mark in rows
        ]
