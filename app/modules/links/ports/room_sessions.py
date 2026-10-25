"""Port for the sessions a right room PIN opens (ROOM-2)."""

from typing import Protocol

SESSION_SECONDS = 12 * 3600


class RoomSessions(Protocol):
    """Opaque tokens handed out after a right PIN; the browser holds one in a cookie."""

    async def open(self, slug: str, pin: str) -> str:
        """Start a session of the room for twelve hours and return its token."""
        ...

    async def pin_of(self, slug: str, token: str) -> str | None:
        """Return the PIN the session was opened with, or None if it is unknown."""
        ...
