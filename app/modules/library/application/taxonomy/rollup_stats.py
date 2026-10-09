"""Move the Redis counters of recent days into `item_stats` (job, idempotent)."""

from datetime import date, timedelta

from app.modules.library.ports.stats_repository import StatsCounters
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

KEEP_DAYS = 2  # counters of today and yesterday stay, older ones are removed


class RollupStats:
    """`library.rollup_stats` (daily 02:10): upsert the counters, drop old keys."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, counters: StatsCounters
    ) -> None:
        """Store the dependencies."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.counters = counters

    async def execute(self) -> int:
        """Roll up today and the two days before; returns the rows written."""
        today = self.clock.now().date()  # the day the counters were written under
        written = 0
        for back in range(KEEP_DAYS, -1, -1):
            day = today - timedelta(days=back)
            written += await self._roll(day, discard=back >= KEEP_DAYS)
        return written

    async def _roll(self, day: date, *, discard: bool) -> int:
        counters = await self.counters.day(day)
        if not counters:
            return 0
        async with self.uow_factory() as uow:
            for item_id, figures in counters.items():
                await uow.stats.upsert_day(
                    item_id,
                    day,
                    figures.opens,
                    figures.readers,
                    figures.offline_saves,
                )
            await uow.commit()
        if discard:
            await self.counters.discard(day, list(counters))
        return len(counters)
