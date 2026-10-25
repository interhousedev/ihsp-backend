"""Port for counting clicks before they are flushed to the database."""

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID


class HitCounter(Protocol):
    """Counts link hits (Redis `links:hits:{link_id}`)."""

    async def hit(self, link_id: UUID) -> None:
        """Count one click or view."""
        ...

    async def drain(self) -> dict[UUID, int]:
        """Atomically take and reset all counters."""
        ...

    async def restore(self, counts: Mapping[UUID, int]) -> None:
        """Put counters back after a failed flush."""
        ...
