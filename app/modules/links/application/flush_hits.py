"""Move click counters from Redis into the database (SL-6)."""

from app.modules.links.ports.hit_counter import HitCounter
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class FlushHits:
    """Drain `links:hits:*` counters and add them to `links.hits`."""

    def __init__(
        self, *, uow_factory: UowFactory, hits: HitCounter, clock: Clock
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.hits = hits
        self.clock = clock

    async def execute(self) -> int:
        """Return how many links got new clicks; counters are restored on failure."""
        counts = await self.hits.drain()
        if not counts:
            return 0
        try:
            async with self.uow_factory() as uow:
                await uow.links.add_hits(counts, self.clock.now())
                await uow.commit()
        except Exception:
            await self.hits.restore(counts)
            raise
        return len(counts)
