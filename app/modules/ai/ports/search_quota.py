"""Port: the day's web search counter of a user."""

from datetime import date
from typing import Protocol
from uuid import UUID


class SearchQuotaStore(Protocol):
    """One counter per user and Tashkent day (`ai:websearch:{user}:{date}`)."""

    async def used(self, user_id: UUID, day: date) -> int:
        """Searches counted that day."""
        ...

    async def add(self, user_id: UUID, day: date, units: int) -> int:
        """Count `units` searches at once and return the new total (kept 48 hours)."""
        ...

    async def remove(self, user_id: UUID, day: date, units: int) -> None:
        """Give `units` back (a failed search is not counted); never below 0."""
        ...
