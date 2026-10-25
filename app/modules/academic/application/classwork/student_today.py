"""Use case: the student's Today dashboard data (WEB-3, UF-WEB-02)."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from app.modules.academic.application.classwork.homework_list import HomeworkList
from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    StudyDays,
    keys_of,
    mark_item,
    require_student,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.records import StudentRecord, TermRecord
from app.modules.academic.domain.classwork.reports import (
    LessonState,
    day_states,
    minutes_until,
)
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.links import LinksApi

NEW_MARKS_LIMIT = 10


class StudentToday:
    """Now and next lesson, the day timeline, due homework, marks and the semester.

    ``due`` is the homework to do: overdue items first, then those due by the next
    study day.
    """

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        lesson_items: LessonItemBuilder,
        homework: HomeworkList,
        study_days: StudyDays,
        links: LinksApi,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items
        self.homework = homework
        self.study_days = study_days
        self.links = links

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return the ``StudentToday`` JSON."""
        now, today = self.clock.now(), local_today(self.clock)
        preferences = await self.people.preferences(actor.user_id)
        locale = str(preferences.locale)
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            keys = keys_of(student)
            todays = await uow.lesson_reader.audience_lessons(keys, today, today)
            next_day = await self.study_days.next_after(
                uow.lesson_reader, student.user_id, keys, today
            )
            states = day_states(todays, now)
            focus = _focus(states)
            upcoming_first: Lesson | None = None
            if focus is None and next_day is not None:
                upcoming_first = await uow.lesson_reader.first_scheduled_on(
                    keys, next_day
                )
            marks = await uow.results.new_marks(
                student.user_id, preferences.seen_marks_at, NEW_MARKS_LIMIT
            )
            term = await uow.results.current_term(today)
            semester = await self._semester(uow, student, term)
        items = await self.lesson_items.build_many(
            [lesson for lesson, _ in states], locale
        )
        lessons = [
            {**item, "state": state}
            for item, (_, state) in zip(items, states, strict=True)
        ]
        card, state = focus if focus else (upcoming_first, None)
        return {
            "now_or_next": await self._now_or_next(card, state, now, locale),
            "lessons": lessons,
            "next_study_day": None if next_day is None else next_day.isoformat(),
            "due": await self.homework.due(actor),
            "new_marks": [mark_item(mark, locale) for mark in marks],
            "semester": semester,
            "synced_at": student.synced_at.isoformat() if student.synced_at else None,
        }

    async def _now_or_next(
        self,
        lesson: Lesson | None,
        state: LessonState | None,
        now: dt.datetime,
        locale: str,
    ) -> dict[str, Any] | None:
        if lesson is None:
            return None
        item = await self.lesson_items.build(lesson, locale)
        minutes: int | None = None
        if state is not None:
            target = lesson.ends_at if state == "now" else lesson.starts_at
            minutes = minutes_until(target, now)
        refs = await self.links.resources_for_lessons([lesson.id])
        count = sum(
            1
            for ref in refs.get(lesson.id, [])
            if ref.role == "material" and not ref.hidden
        )
        return {**item, "minutes_left": minutes, "materials_count": count}

    async def _semester(
        self, uow: ViewUnitOfWork, student: StudentRecord, term: TermRecord | None
    ) -> dict[str, Any]:
        number = student.current_semester
        gpa: float | None = None
        change: float | None = None
        if number is not None:
            gpas = await uow.results.gpas([student.user_id], number)
            gpa = gpas.get(student.user_id)
            if number > 1 and gpa is not None:
                before = await uow.results.gpas([student.user_id], number - 1)
                previous = before.get(student.user_id)
                change = None if previous is None else round(gpa - previous, 2)
        absences = 0
        if term is not None:
            absences = await uow.reports.absence_count(
                student.user_id, term.starts_on, term.ends_on
            )
        return {
            "semester": number,
            "gpa": gpa,
            "gpa_change": change,
            "absences": absences,
        }


def _focus(
    states: list[tuple[Lesson, LessonState]],
) -> tuple[Lesson, LessonState] | None:
    for kind in ("now", "next"):
        for lesson, state in states:
            if state == kind:
                return lesson, state
    return None
