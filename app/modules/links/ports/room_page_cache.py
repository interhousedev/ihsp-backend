"""Port for the rendered room page cache."""

from datetime import date
from typing import Protocol


class RoomPageCache(Protocol):
    """Caches the rendered HTML of a room day (Redis `room:{slug}:{date}`)."""

    async def get(self, slug: str, day: date) -> str | None:
        """Return the cached HTML or None."""
        ...

    async def put(self, slug: str, day: date, html: str) -> None:
        """Cache the HTML for ten minutes."""
        ...

    async def invalidate(self, slug: str, day: date) -> None:
        """Forget the cached page of the room day."""
        ...
