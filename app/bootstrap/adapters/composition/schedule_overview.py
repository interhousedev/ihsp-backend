"""ScheduleOverview over the academic schedule use cases."""

import datetime as dt
from uuid import UUID

from app.interfaces.http.v1.composition.ports import DayCounts
from app.modules.academic.application.schedule.current_term import CurrentTerm
from app.modules.academic.application.schedule.list_groups import ListGroups
from app.modules.academic.application.schedule.list_lessons import (
    MAX_LIMIT,
    ListLessons,
)
from app.modules.academic.application.schedule.ports.reader import LessonFilters
from app.shared.actor import Actor

# A school day has a few hundred lessons: this many pages is far beyond any real day.
MAX_PAGES = 50


class ScheduleOverviewAdapter:
    """Composition <- academic schedule: term bounds, day counts, active groups."""

    def __init__(
        self,
        current_term: CurrentTerm,
        list_lessons: ListLessons,
        list_groups: ListGroups,
    ) -> None:
        """Keep the three schedule use cases."""
        self._current_term = current_term
        self._list_lessons = list_lessons
        self._list_groups = list_groups

    async def term_bounds(self, day: dt.date) -> tuple[dt.date, dt.date] | None:
        """Return (starts_on, ends_on) of the term that applies on the day."""
        term = await self._current_term.execute(day)
        return None if term is None else (term.starts_on, term.ends_on)

    async def day_counts(self, actor: Actor, day: dt.date) -> DayCounts:
        """Count the day's lessons over all groups by paging through `ListLessons`."""
        lessons = cancelled = teacher_needed = 0
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = await self._list_lessons.execute(
                actor, LessonFilters(start=day, end=day), cursor=cursor, limit=MAX_LIMIT
            )
            for item in page.items:
                lessons += 1
                if item["status"] == "cancelled":
                    cancelled += 1
                elif item["teacher"] is None:
                    teacher_needed += 1
            cursor = page.next_cursor
            if cursor is None:
                break
        return DayCounts(
            lessons=lessons, cancelled=cancelled, teacher_needed=teacher_needed
        )

    async def active_group_ids(self) -> list[UUID]:
        """Return the ids of the active groups."""
        return [group.id for group in await self._list_groups.execute("active")]
