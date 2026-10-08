"""Cache of rendered room pages (README -> Redis keys ``room:{slug}:{date}``)."""

from collections.abc import Collection
from typing import Protocol


class RoomPageCache(Protocol):
    """Drops cached room pages when a lesson or PIN of the room changes."""

    async def invalidate(self, slugs: Collection[str]) -> None:
        """Forget the cached pages of the rooms."""
        ...
