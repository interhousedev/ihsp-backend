"""``ExcuseStatusQuery``: is the student officially excused right now."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.excuses.ports import (
    ExcuseDirectory,
    ExcuseUowFactory,
)
from app.shared.clock import to_local
from app.shared.contracts.academic import ScheduleQueries
from app.shared.contracts.excuses import ExcuseStatus


class ExcuseStatusQuery:
    """Implements the excuses contract read by the Faces module."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        directory: ExcuseDirectory,
        schedule: ScheduleQueries,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.directory = directory
        self.schedule = schedule

    async def status(self, student_id: UUID, at: dt.datetime) -> ExcuseStatus:
        """Return the state of the student at ``at``.

        ``excused_now`` is true when an approved excuse includes the local day
        and, for a partial one, a lesson of it is running at ``at``.
        """
        day = to_local(at).date()
        context = await self.directory.student_context(student_id)
        async with self.uow_factory() as uow:
            found = await uow.excuses.covering([student_id], day)
        lessons = [
            lesson
            for lesson in await self.schedule.lessons_for_student(student_id, day, day)
            if lesson.status == "scheduled"
        ]
        running = [x for x in lessons if x.starts_at <= at < x.ends_at]
        excuse_id: UUID | None = None
        until: dt.date | None = None
        for excuse in found:
            if excuse.lesson_ids or excuse.subject_ids:
                hit = any(excuse.covers(x.date, x.id, x.subject_id) for x in running)
            else:
                hit = True
            if hit:
                excuse_id, until = excuse.id, excuse.ends_on
                break
        return ExcuseStatus(
            student_id=student_id,
            excused_now=excuse_id is not None,
            excuse_id=excuse_id,
            until=until,
            in_lesson_time=bool(running),
            curator_id=context.curator_id if context else None,
            group_id=context.group_id if context else None,
        )
