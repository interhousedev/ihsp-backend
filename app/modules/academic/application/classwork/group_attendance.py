"""Use case: the curator's attendance report of a group (STF-13, UF-STF-11)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.lookup import ensure_curator
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.attendance_reports import (
    GroupView,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.report_format import ReportFormatter
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import ScheduleQueries


class GroupAttendance:
    """Per student, subject, day or lesson, with not-taken lessons apart."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        formatter: ReportFormatter,
        schedule: ScheduleQueries,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.formatter = formatter
        self.schedule = schedule

    async def execute(
        self,
        actor: Actor,
        group_id: UUID,
        view: GroupView,
        start: dt.date | None,
        end: dt.date | None,
    ) -> dict[str, Any]:
        """Return the ``AttendanceReport`` JSON; the default range is the term."""
        await ensure_curator(self.schedule, actor, group_id)
        now, today = self.clock.now(), local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            if start is None or end is None:
                term = await uow.results.current_term(today)
                start = start or (term.starts_on if term else today)
                end = end or (term.ends_on if term else today)
            rows = await uow.reports.group_report(group_id, view, start, end, now)
        return await self.formatter.format(view, rows, locale, start, end)
