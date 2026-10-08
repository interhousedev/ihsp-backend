"""A teacher's timetable for a date range (STF-3)."""

import datetime as dt
from typing import Any

from app.modules.academic.application.schedule.common import (
    caller_locale,
    today,
)
from app.modules.academic.application.schedule.date_range import resolve_range
from app.modules.academic.application.schedule.lesson_items import build_lesson_items
from app.modules.academic.application.schedule.ports.reader import ScheduleReader
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory


class GetStaffTimetable:
    """Return the lessons the actor teaches."""

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
        views = await self.reader.lessons_for_teacher(
            actor.user_id, first, last, locale
        )
        return await build_lesson_items(views, self.identity)
