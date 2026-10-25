"""Use case: Administration's attendance report (ADM-12, UF-ADM-09)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.attendance_reports import (
    AdminView,
)
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.report_format import ReportFormatter
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today


class AttendanceReport:
    """Per group, student, subject or teacher."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        formatter: ReportFormatter,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.formatter = formatter

    async def execute(
        self,
        actor: Actor,
        view: AdminView,
        start: dt.date | None,
        end: dt.date | None,
        group_id: UUID | None,
    ) -> dict[str, Any]:
        """Return the ``AttendanceReport`` JSON; the default range is the term."""
        actor.require(Role.ADMIN)
        now, today = self.clock.now(), local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            if start is None or end is None:
                term = await uow.results.current_term(today)
                start = start or (term.starts_on if term else today)
                end = end or (term.ends_on if term else today)
            rows = await uow.reports.admin_report(view, start, end, group_id, now)
        return await self.formatter.format(view, rows, locale, start, end)
