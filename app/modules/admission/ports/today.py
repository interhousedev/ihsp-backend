"""Port: the streak days and the season override of the Today feed."""

import datetime as dt
from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.today import SeasonKey


class TodayRepository(Protocol):
    """Activity days and season overrides."""

    async def activity_days(self, student_id: UUID, since: dt.date) -> set[dt.date]:
        """Days on or after `since` on which the student did something."""
        ...

    async def touch(self, student_ids: Collection[UUID], day: dt.date) -> None:
        """Record `day` as active for each student (idempotent)."""
        ...

    async def season_override(self, student_id: UUID) -> SeasonKey | None:
        """The season the student fixed, if any."""
        ...

    async def set_season_override(
        self, student_id: UUID, key: SeasonKey | None
    ) -> None:
        """Fix a season, or None to go back to the automatic one."""
        ...

    async def snoozes(self, student_id: UUID) -> dict[str, tuple[int, dt.date]]:
        """Per action key: how often it was snoozed and until which day."""
        ...

    async def save_snooze(
        self, student_id: UUID, key: str, count: int, until: dt.date
    ) -> None:
        """Insert or replace the snooze of one action."""
        ...
