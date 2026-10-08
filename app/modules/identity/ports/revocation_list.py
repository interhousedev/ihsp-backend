"""Port: revoked sessions and connectors, and the cached auth epoch."""

from typing import Protocol
from uuid import UUID


class RevocationList(Protocol):
    """IDs of sessions or connectors revoked within the access token lifetime."""

    async def revoke(self, identifier: UUID | str, *, ttl: int | None = None) -> None:
        """Mark a session or connector id as revoked."""
        ...

    async def is_revoked(self, identifier: UUID | str) -> bool:
        """True while the id is on the list."""
        ...


class AuthEpochCache(Protocol):
    """Current auth_epoch per user, checked on every request."""

    async def get(self, user_id: UUID) -> int | None:
        """Return the cached epoch or None."""
        ...

    async def set(self, user_id: UUID, epoch: int) -> None:
        """Cache the epoch."""
        ...
