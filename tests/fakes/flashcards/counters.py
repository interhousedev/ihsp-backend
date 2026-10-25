"""In-memory daily counters."""

from datetime import date
from uuid import UUID

from app.modules.flashcards.domain.study import DailyUsage
from app.modules.flashcards.ports.daily_counters import CounterKind


class InMemoryDailyCounters:
    """Implements DailyCounters without Redis."""

    def __init__(self) -> None:
        """Start with zero counters."""
        self.values: dict[tuple[UUID, UUID, date, str], int] = {}

    async def usage(self, owner_id: UUID, set_id: UUID, day: date) -> DailyUsage:
        """Return the counters of one day."""
        return DailyUsage(
            new=self.values.get((owner_id, set_id, day, "new"), 0),
            review=self.values.get((owner_id, set_id, day, "review"), 0),
        )

    async def increment(
        self, owner_id: UUID, set_id: UUID, day: date, kind: CounterKind
    ) -> None:
        """Count one."""
        key = (owner_id, set_id, day, kind)
        self.values[key] = self.values.get(key, 0) + 1
