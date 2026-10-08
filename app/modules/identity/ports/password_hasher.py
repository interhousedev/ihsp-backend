"""Port: password hashing (Argon2id, off the event loop)."""

from typing import Protocol


class PasswordHasher(Protocol):
    """Hashes and checks passwords."""

    async def hash(self, password: str) -> str:
        """Return the encoded hash."""
        ...

    async def verify(self, password_hash: str | None, password: str) -> bool:
        """True on a match; a missing hash burns the same time and returns False."""
        ...

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the stored parameters are outdated."""
        ...
