"""Port for limiting wrong room PIN attempts."""

from typing import Protocol


class PinLimiter(Protocol):
    """Counts wrong PINs per room and IP (ROOM-5): 5 per 15 minutes."""

    async def retry_after(self, slug: str, ip: str | None) -> int | None:
        """Return the seconds to wait if the IP used its attempts, else None."""
        ...

    async def record_failure(self, slug: str, ip: str | None) -> None:
        """Count one wrong PIN."""
        ...
