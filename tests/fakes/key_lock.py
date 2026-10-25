"""An in-memory KeyLock for one process."""

from uuid import uuid4


class InMemoryKeyLock:
    """Holds keys in a dict; TTLs are not simulated."""

    def __init__(self) -> None:
        """Start with no held keys."""
        self.held: dict[str, str] = {}

    async def acquire(self, key: str, ttl_seconds: int) -> str | None:
        """Take the key or say it is held."""
        if key in self.held:
            return None
        token = uuid4().hex
        self.held[key] = token
        return token

    async def release(self, key: str, token: str) -> None:
        """Free the key when the token matches."""
        if self.held.get(key) == token:
            del self.held[key]
