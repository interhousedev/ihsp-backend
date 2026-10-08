"""AttendanceStats over the classwork attendance report (`view=group`)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.classwork.attendance_report import (
    AttendanceReport,
)
from app.shared.actor import Actor


class AttendanceStatsAdapter:
    """Composition <- academic classwork: absence rate per group."""

    def __init__(self, attendance_report: AttendanceReport) -> None:
        """Keep the attendance report use case."""
        self._report = attendance_report

    async def group_absence_rates(
        self, actor: Actor, start: dt.date, end: dt.date
    ) -> dict[UUID, float | None]:
        """Return the `rate` of each row of the group report, keyed by group id."""
        report = await self._report.execute(actor, "group", start, end, None)
        rates: dict[UUID, float | None] = {}
        for row in report["rows"]:
            rate = row["rate"]
            rates[UUID(row["key"])] = None if rate is None else float(rate)
        return rates
