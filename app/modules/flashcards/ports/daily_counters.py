"""Port: how many cards were introduced and reviewed today (WEB-23 daily limits)."""

from datetime import date
from typing import Literal, Protocol
from uuid import UUID

from app.modules.flashcards.domain.study import DailyUsage

CounterKind = Literal["new", "review"]


class DailyCounters(Protocol):
    """Per user, set and study day."""

    async def usage(self, owner_id: UUID, set_id: UUID, day: date) -> DailyUsage:
        """Return the counters of one day (zeros when nothing was studied)."""
        ...

    async def increment(
        self, owner_id: UUID, set_id: UUID, day: date, kind: CounterKind
    ) -> None:
        """Count one introduced new card or one finished review."""
        ...
