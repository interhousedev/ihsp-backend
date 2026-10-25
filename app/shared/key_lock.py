"""Port: a lock on a named key, shared by every process (the Redis one in prod)."""

from typing import Protocol


class KeyLock(Protocol):
    """Take a key for a while; only the holder's token can free it early."""

    async def acquire(self, key: str, ttl_seconds: int) -> str | None:
        """Return a token when the key was free, None when someone holds it."""
        ...

    async def release(self, key: str, token: str) -> None:
        """Free the key if `token` still holds it."""
        ...
