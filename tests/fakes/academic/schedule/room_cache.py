"""Fake room page cache that records invalidations."""

from collections.abc import Collection


class FakeRoomPageCache:
    """Records the slugs whose cached pages were dropped."""

    def __init__(self) -> None:
        """Start with nothing invalidated."""
        self.invalidated: list[str] = []

    async def invalidate(self, slugs: Collection[str]) -> None:
        """Remember the slugs."""
        self.invalidated.extend(slugs)
