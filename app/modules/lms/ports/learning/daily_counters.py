"""Port: how many flash cards a learner studied today."""

from datetime import date
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.cards import DailyUsage


class DailyCounters(Protocol):
    """Daily limits of flash card blocks (Redis ``fc:day:{user}:{block}:{date}``)."""

    async def get(self, user_id: UUID, block_id: str, day: date) -> DailyUsage:
        """Return the cards introduced and reviewed today."""
        ...

    async def add(
        self, user_id: UUID, block_id: str, day: date, *, new: int = 0, review: int = 0
    ) -> None:
        """Count cards studied today."""
        ...
