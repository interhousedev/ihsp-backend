"""Use case: the teacher's Today page (STF-2, UF-STF-02)."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ReaderUnitOfWork,
)
from app.modules.academic.domain.classwork.reports import day_states
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today


class StaffToday:
    """Current or next lesson, today's lessons with badges, and what was missed."""

    def __init__(
        self,
        uow_factory: Callable[[], ReaderUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        lesson_items: LessonItemBuilder,
        edit_days: int,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items
        self.edit_days = edit_days

    async def execute(self, actor: Actor) -> dict[str, Any]:
        """Return the ``StaffToday`` JSON."""
        now, today = self.clock.now(), local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            lessons = await uow.lesson_reader.teacher_lessons(
                actor.user_id, today, today
            )
            missed = await uow.lesson_reader.missing_attendance(
                actor.user_id, today - dt.timedelta(days=self.edit_days), today, now
            )
        states = day_states(lessons, now)
        items = await self.lesson_items.build_many(
            [lesson for lesson, _ in states], locale
        )
        focus = next(
            (i for i, (_, s) in enumerate(states) if s in ("now", "next")), None
        )
        day = []
        for item, (lesson, _) in zip(items, states, strict=True):
            day.append(
                {
                    **item,
                    "attendance_missing": (
                        lesson.scheduled
                        and lesson.ends_at <= now
                        and not lesson.submitted
                    ),
                    "homework_missing": lesson.scheduled and not lesson.has_homework,
                }
            )
        return {
            "now_or_next": None if focus is None else items[focus],
            "lessons": day,
            "needs_attention": await self.lesson_items.build_many(missed, locale),
        }
