"""The caseload deadlines timeline of a staff member (`GET /staff/deadlines`)."""

import datetime as dt
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.calendar import CalendarService
from app.modules.admission.application.staff import CaseloadFilters, StaffService
from app.modules.admission.application.tasks import TaskService
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.permissions import Permission
from app.shared.clock import Clock

WINDOW_BEFORE_DAYS: Final = 7
WINDOW_AFTER_DAYS: Final = 120
MAX_STUDENTS: Final = 200


@dataclass(frozen=True, slots=True)
class StudentDeadline:
    """One dated item of one student on the caseload."""

    student_id: UUID
    student_name: str | None
    group_name: str | None
    date: dt.date
    title: str
    kind: str
    href: str
    list_entry_id: UUID | None = None
    by_staff: bool = False


class StaffTimelineService:
    """Deadlines and counselor tasks of the students the caller reaches."""

    def __init__(
        self,
        staff: StaffService,
        calendar: CalendarService,
        tasks: TaskService,
        access: AccessPolicy,
        clock: Clock,
    ) -> None:
        """Keep the collaborators."""
        self._staff = staff
        self._calendar = calendar
        self._tasks = tasks
        self._access = access
        self._clock = clock

    async def get(
        self, ctx: AdmissionContext, scope: str, locale: str
    ) -> list[StudentDeadline]:
        """`mine`: students assigned to the caller one by one; `all`: all reached."""
        items = await self._staff.caseload(ctx, CaseloadFilters())
        if scope == "mine":
            direct = self._access.scope(ctx).student_ids
            items = [i for i in items if i.row.student_id in direct]
        today = self._tasks.today()
        start = today - dt.timedelta(days=WINDOW_BEFORE_DAYS)
        end = today + dt.timedelta(days=WINDOW_AFTER_DAYS)
        out: list[StudentDeadline] = []
        for item in items[:MAX_STUDENTS]:
            sid = item.row.student_id
            base = (sid, item.student_name, item.row.group_name)
            out += await self._calendar_items(ctx, base, start, end, locale)
            out += await self._task_items(ctx, base, start, end)
        return sorted(out, key=lambda d: (d.date, d.student_name or "", d.title))

    async def _calendar_items(
        self,
        ctx: AdmissionContext,
        base: tuple[UUID, str | None, str | None],
        start: dt.date,
        end: dt.date,
        locale: str,
    ) -> list[StudentDeadline]:
        res = await self._access.resolve(ctx, base[0])
        if Permission.LIST_READ not in res.permissions:
            return []
        entries = await self._calendar.entries(ctx, start, end, locale, base[0])
        return [
            StudentDeadline(
                *base,
                e.day,
                e.title,
                e.source,
                e.url_path or "/calendar/",
                e.list_entry_id,
            )
            for e in entries
        ]

    async def _task_items(
        self,
        ctx: AdmissionContext,
        base: tuple[UUID, str | None, str | None],
        start: dt.date,
        end: dt.date,
    ) -> list[StudentDeadline]:
        try:
            tasks = await self._tasks.list_for(ctx, base[0])
        except (AdmissionForbiddenError, AdmissionNotFoundError):
            return []
        return [
            StudentDeadline(
                *base,
                t.deadline,
                t.title,
                "task",
                f"/tasks/?task={t.id}",
                t.list_entry_id,
                t.created_by in ("counselor", "mentor"),
            )
            for t in tasks
            if t.deadline is not None
            and t.status != "done"
            and start <= t.deadline <= end
        ]
