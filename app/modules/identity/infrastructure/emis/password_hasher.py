"""Argon2id password hashing (CPU-bound, so it runs in a worker thread)."""

import asyncio

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2PasswordHasher:
    """Hashes with the argon2-cffi defaults (Argon2id, RFC 9106 low-memory profile)."""

    def __init__(self) -> None:
        """Create the hasher."""
        self._hasher = Argon2()

    async def hash(self, password: str) -> str:
        """Return the encoded Argon2id hash."""
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return True if the password matches the hash."""

        def check() -> bool:
            try:
                return self._hasher.verify(password_hash, password)
            except (VerificationError, InvalidHashError):
                return False

        return await asyncio.to_thread(check)
