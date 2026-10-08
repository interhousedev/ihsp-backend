"""Port: short-lived JSON tickets in Redis."""

from typing import Any, Protocol


class TicketStore(Protocol):
    """Stores small JSON documents under a key with a TTL."""

    async def put(self, key: str, data: dict[str, Any], *, ttl: int) -> None:
        """Store (replace) a document."""
        ...

    async def get(self, key: str) -> dict[str, Any] | None:
        """Read a document."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a document."""
        ...
