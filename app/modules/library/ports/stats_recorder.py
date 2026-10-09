"""Port: counting opens and offline saves (Redis counters rolled up daily)."""

from typing import Protocol
from uuid import UUID


class StatsRecorder(Protocol):
    """Fire-and-forget counters; they never fail a request."""

    async def opened(self, item_id: UUID, user_id: UUID | None) -> None:
        """Count one open of the item; `user_id` feeds the distinct-readers count."""
        ...

    async def offline_saved(self, item_id: UUID) -> None:
        """Count one 'saved for offline' of the item."""
        ...
