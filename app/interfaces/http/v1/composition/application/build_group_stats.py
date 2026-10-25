"""Use case: attendance rate and average GPA per group (ADM-6)."""

import datetime as dt
from uuid import UUID

from app.interfaces.http.v1.composition.ports import (
    AttendanceStats,
    JsonObject,
    ScheduleOverview,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today
from app.shared.contracts.academic import MarksQueries, ScheduleQueries


class BuildGroupStats:
    """Stats for the groups list: this term's attendance and the current GPA."""

    def __init__(
        self,
        *,
        overview: ScheduleOverview,
        attendance: AttendanceStats,
        schedule: ScheduleQueries,
        marks: MarksQueries,
        clock: Clock,
    ) -> None:
        """Store the collaborators."""
        self.overview = overview
        self.attendance = attendance
        self.schedule = schedule
        self.marks = marks
        self.clock = clock

    async def execute(self, actor: Actor) -> list[JsonObject]:
        """Return `{group_id, attendance_rate, average_gpa}` for every active group."""
        actor.require(Role.ADMIN)
        today = local_today(self.clock)
        absence = await self._absence_rates(actor, today)
        rows: list[JsonObject] = []
        for group_id in await self.overview.active_group_ids():
            rate = absence.get(group_id)
            rows.append(
                {
                    "group_id": group_id,
                    # Reports count absences; the page shows how many were present.
                    "attendance_rate": None if rate is None else round(1 - rate, 4),
                    "average_gpa": await self._average_gpa(group_id),
                }
            )
        return rows

    async def _absence_rates(
        self, actor: Actor, today: dt.date
    ) -> dict[UUID, float | None]:
        """Absence rates from the start of the term to today ({} outside a term)."""
        bounds = await self.overview.term_bounds(today)
        if bounds is None:
            return {}
        start, end = bounds[0], min(today, bounds[1])
        if end < start:
            return {}
        return await self.attendance.group_absence_rates(actor, start, end)

    async def _average_gpa(self, group_id: UUID) -> float | None:
        """Average the GPA of the group's students that have one."""
        user_ids = await self.schedule.group_user_ids([group_id])
        if not user_ids:
            return None
        gpas = await self.marks.gpa_for_users(user_ids, None)
        values = [gpa for gpa in gpas.values() if gpa is not None]
        return round(sum(values) / len(values), 2) if values else None
