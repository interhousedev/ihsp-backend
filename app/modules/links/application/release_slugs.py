"""Free the slugs of links revoked more than 90 days ago (SL-7)."""

from datetime import timedelta

from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

RELEASE_AFTER = timedelta(days=90)


class ReleaseSlugs:
    """Set `slug_released_at`; the rows stay as evidence."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> int:
        """Return how many slugs were released."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            released = await uow.links.release_revoked_before(now - RELEASE_AFTER, now)
            await uow.commit()
        return released
