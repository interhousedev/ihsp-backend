"""Use case: teachers with lessons that have no attendance (UF-ADM-09)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lesson_items import LessonItemBuilder
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ReaderUnitOfWork,
)
from app.modules.academic.domain.classwork.lesson import Lesson
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today


class MissingAttendance:
    """Group finished lessons without a submitted list by their teacher."""

    def __init__(
        self,
        uow_factory: Callable[[], ReaderUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        lesson_items: LessonItemBuilder,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.lesson_items = lesson_items

    async def execute(
        self, actor: Actor, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        """Return ``{"teacher": PersonRef, "lessons": LessonItem[]}`` rows."""
        actor.require(Role.ADMIN)
        today = local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            lessons = await uow.lesson_reader.missing_attendance(
                None,
                start or today - dt.timedelta(days=7),
                end or today,
                self.clock.now(),
            )
        by_teacher: dict[UUID, list[Lesson]] = {}
        for lesson in lessons:
            if lesson.teacher_id is not None:
                by_teacher.setdefault(lesson.teacher_id, []).append(lesson)
        teachers = await self.people.people(by_teacher)
        rows: list[dict[str, Any]] = []
        for teacher_id, group in by_teacher.items():
            person = teachers.get(teacher_id)
            if person is None:
                continue
            rows.append(
                {
                    "teacher": person.to_json(),
                    "lessons": await self.lesson_items.build_many(group, locale),
                }
            )
        rows.sort(
            key=lambda row: (row["teacher"]["last_name"], row["teacher"]["first_name"])
        )
        return rows
