"""Port for the short-lived store of guest bot answers shared by link."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredGuestAnswer:
    """An answer kept for the public page: text with valid blocks, creation time."""

    text: str
    created_at: datetime


class GuestAnswerStore(Protocol):
    """Keeps guest answers under a random token for a limited time."""

    async def put(
        self, token: str, answer: StoredGuestAnswer, ttl_seconds: int
    ) -> None:
        """Save the answer; it disappears after `ttl_seconds`."""
        ...

    async def get(self, token: str) -> StoredGuestAnswer | None:
        """Return the answer or None when unknown or expired."""
        ...
