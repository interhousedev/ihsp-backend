"""Use case: the student's homework lists (WEB-18, UF-WEB-13)."""

import datetime as dt
from collections.abc import Callable
from typing import Any, Literal

from app.modules.academic.application.classwork.homework_items import (
    HomeworkItemBuilder,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TodoUnitOfWork,
)
from app.modules.academic.application.classwork.student_context import (
    StudyDays,
    keys_of,
    require_student,
)
from app.modules.academic.domain.classwork.homework_rules import (
    DONE_RETENTION_DAYS,
    bucket,
)
from app.modules.academic.domain.classwork.records import HomeworkRecord
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today

Status = Literal["upcoming", "later", "done"]
HISTORY_DAYS = 90


class HomeworkList:
    """Sort the student's homework into Upcoming, Later and Done."""

    def __init__(
        self,
        uow_factory: Callable[[], TodoUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        items: HomeworkItemBuilder,
        study_days: StudyDays,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.items = items
        self.study_days = study_days

    async def records(self, actor: Actor, status: Status) -> list[HomeworkRecord]:
        """Return the matching records in display order."""
        now = self.clock.now()
        today = local_today(self.clock)
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            keys = keys_of(student)
            found = await uow.lesson_reader.homework_records(
                student.user_id, keys, today - dt.timedelta(days=HISTORY_DAYS)
            )
            next_day = await self.study_days.next_after(
                uow.lesson_reader, student.user_id, keys, today
            )
        cutoff = now - dt.timedelta(days=DONE_RETENTION_DAYS)
        picked = []
        for record in found:
            done_at = record.todo.done_at if record.todo else None
            where = bucket(done_at, record.lesson.homework_due_date, today, next_day)
            if where != status:
                continue
            if status == "done" and done_at is not None and done_at < cutoff:
                continue
            picked.append(record)
        return _ordered(picked, status)

    async def execute(self, actor: Actor, status: Status) -> list[dict[str, Any]]:
        """Return ``HomeworkItem`` JSON for the chosen list."""
        records = await self.records(actor, status)
        locale = await self.people.locale(actor.user_id)
        return await self.items.build_many(records, locale)


def _ordered(records: list[HomeworkRecord], status: Status) -> list[HomeworkRecord]:
    far = dt.date.max
    if status == "done":
        epoch = dt.datetime.min.replace(tzinfo=dt.UTC)
        return sorted(
            records,
            key=lambda r: r.todo.done_at if r.todo and r.todo.done_at else epoch,
            reverse=True,
        )
    return sorted(
        records,
        key=lambda r: (
            r.lesson.homework_due_date or far,
            r.lesson.date,
            r.lesson.period,
        ),
    )
