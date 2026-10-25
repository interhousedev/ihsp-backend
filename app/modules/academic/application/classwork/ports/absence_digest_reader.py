"""Port: what the curator digest needs to know about a school day (WO-4)."""

import datetime as dt
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.lesson import Lesson


class AbsenceDigestReader(Protocol):
    """Queries over one day's lessons and the groups' curators."""

    async def last_lesson_end(self, day: dt.date) -> dt.datetime | None:
        """Latest ``ends_at`` among the day's scheduled lessons."""
        ...

    async def lessons_with_absences(self, day: dt.date) -> list[Lesson]:
        """Lessons of the day taken on the platform with at least one absent student."""
        ...

    async def group_curators(
        self, group_ids: Sequence[UUID]
    ) -> dict[UUID, UUID | None]:
        """Curator user id of each group (None when it has none)."""
        ...
