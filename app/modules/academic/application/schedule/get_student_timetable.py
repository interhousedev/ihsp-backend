"""A student's timetable for a date range (WEB-5)."""

import datetime as dt
from dataclasses import asdict
from typing import Any

from app.modules.academic.application.schedule.common import (
    caller_locale,
    today,
)
from app.modules.academic.application.schedule.date_range import resolve_range
from app.modules.academic.application.schedule.lesson_items import build_lesson_items
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.modules.academic.domain.schedule.subgroup_marks import place_lessons
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class GetStudentTimetable:
    """Return the student's lessons, projecting from the timetable past the horizon.

    Lessons of the other subgroup fill slots the student's own subgroup leaves
    free; each item has `subgroup` (None for the whole group, else the subgroup id,
    name and whether it is the student's own).
    """

    def __init__(
        self, reader: ScheduleReader, identity: IdentityDirectory, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self.reader = reader
        self.identity = identity
        self.clock = clock

    async def execute(
        self, actor: Actor, start: dt.date | None, end: dt.date | None
    ) -> list[dict[str, Any]]:
        """Return LessonItem dicts ordered by time."""
        first, last = resolve_range(start, end, today(self.clock))
        locale = await caller_locale(self.identity, actor)
        placement = await self.reader.student_placement(actor.user_id)
        if placement is None:
            return []
        group_id, subgroup = placement
        views = await self.reader.projected_for_group(group_id, first, last, locale)
        name = next(
            (
                v.audience_groups[group_id]
                for v in views
                if group_id in v.audience_groups
            ),
            str(group_id),
        )
        placed = place_lessons([v.ref for v in views], group_id, name, subgroup)
        marks = {ref.id: mark for ref, mark in placed}
        kept = [v for v in views if v.ref.id in marks]
        items = await build_lesson_items(kept, self.identity)
        for view, item in zip(kept, items, strict=True):
            mark = marks[view.ref.id]
            item["subgroup"] = None if mark is None else asdict(mark)
        return items
