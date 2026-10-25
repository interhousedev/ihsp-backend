"""Use case: Administration sees open and done work-offs by key (WO-8)."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import ViewUnitOfWork
from app.modules.academic.application.classwork.work_off_items import (
    ensure_admin,
    names_of,
)
from app.modules.academic.domain.classwork.work_off_views import GroupBy
from app.shared.actor import Actor
from app.shared.clock import Clock, local_today

DEFAULT_DAYS = 30


class WorkOffStats:
    """Counts per subject, teacher, group or student."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people

    async def execute(
        self,
        actor: Actor,
        *,
        group_by: GroupBy,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> dict[str, Any]:
        """Return the statistics dict.

        Shape: ``{group_by, from, to, total_open, rows}`` where each row is
        ``{key, name, open_count, done_count}``.

        Rows are sorted by open count, biggest first. Dates default to the last
        30 days.

        Raises:
            ForbiddenError: the actor is not an administrator.
        """
        ensure_admin(actor)
        to_day = end or local_today(self.clock)
        from_day = start or to_day - dt.timedelta(days=DEFAULT_DAYS)
        async with self.uow_factory() as uow:
            stats = await uow.work_off_reader.stats(group_by, from_day, to_day)
        people = {}
        if group_by in ("teacher", "student"):
            people = await names_of(self.people, (row.key for row in stats))
        named = sorted(
            ((row.label or people.get(row.key, "?"), row) for row in stats),
            key=lambda pair: (-pair[1].open_count, pair[0].casefold()),
        )
        rows = [
            {
                "key": str(row.key),
                "name": name,
                "open_count": row.open_count,
                "done_count": row.done_count,
            }
            for name, row in named
        ]
        return {
            "group_by": group_by,
            "from": from_day.isoformat(),
            "to": to_day.isoformat(),
            "total_open": sum(row.open_count for row in stats),
            "rows": rows,
        }
