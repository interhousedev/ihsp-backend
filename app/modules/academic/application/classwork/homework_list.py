"""Use case: the student's homework lists (WEB-3, WEB-18, UF-WEB-13)."""

import datetime as dt
from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from app.modules.academic.application.classwork.homework_items import (
    HomeworkItemBuilder,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.lesson_reader import LessonReader
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
from app.modules.academic.domain.classwork.records import HomeworkRecord, StudentRecord
from app.shared.actor import Actor
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock, local_today

Status = Literal["overdue", "upcoming", "later", "done"]
DUE: tuple[Status, ...] = ("overdue", "upcoming")
HISTORY_DAYS = 90


class HomeworkList:
    """Sort the student's homework into Overdue, Upcoming, Later and Done."""

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

    async def records(self, actor: Actor, *statuses: Status) -> list[HomeworkRecord]:
        """Return the records of the chosen lists, the lists in the order given."""
        today = local_today(self.clock)
        async with self.uow_factory() as uow:
            student = await require_student(uow, actor.user_id)
            keys = keys_of(student)
            next_day = await self.study_days.next_after(
                uow.lesson_reader, student.user_id, keys, today
            )
            return await self.pick(uow.lesson_reader, student, next_day, statuses)

    async def pick(
        self,
        reader: LessonReader,
        student: StudentRecord,
        next_day: dt.date | None,
        statuses: tuple[Status, ...],
    ) -> list[HomeworkRecord]:
        """Return the chosen lists for a student whose next study day is known."""
        now = self.clock.now()
        today = local_today(self.clock)
        found = await reader.homework_records(
            student.user_id,
            keys_of(student),
            today - dt.timedelta(days=HISTORY_DAYS),
        )
        cutoff = now - dt.timedelta(days=DONE_RETENTION_DAYS)
        picked: dict[Status, list[HomeworkRecord]] = {s: [] for s in statuses}
        for record in found:
            done_at = record.todo.done_at if record.todo else None
            where = bucket(done_at, record.lesson.homework_due_date, today, next_day)
            if where not in picked:
                continue
            if where == "done" and done_at is not None and done_at < cutoff:
                continue
            picked[where].append(record)
        return [r for s in statuses for r in _ordered(picked[s], s)]

    async def execute(
        self,
        actor: Actor,
        status: Status,
        *,
        subject_id: UUID | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
    ) -> list[dict[str, Any]]:
        """Return ``HomeworkItem`` JSON for the chosen list.

        `subject_id` keeps one subject's homework; `date_from` and `date_to` (both
        inclusive) keep the homework whose due date is in that range, so homework
        without a due date is left out when a range is given.

        Raises:
            ValidationFailedError: `date_from` is after `date_to`.
        """
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValidationFailedError(
                params={"details": ["from: must not be after to"]}
            )
        records = await self.records(actor, status)
        if subject_id is not None:
            records = [r for r in records if r.lesson.subject_id == subject_id]
        if date_from is not None or date_to is not None:
            records = [
                r
                for r in records
                if (due := r.lesson.homework_due_date) is not None
                and (date_from is None or due >= date_from)
                and (date_to is None or due <= date_to)
            ]
        locale = await self.people.locale(actor.user_id)
        return await self.items.build_many(records, locale)

    async def due(self, actor: Actor) -> list[dict[str, Any]]:
        """Return the open items that need doing: overdue first, then upcoming."""
        records = await self.records(actor, *DUE)
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
