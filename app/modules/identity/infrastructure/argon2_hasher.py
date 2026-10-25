"""Argon2id password hashing, run in a thread (it is CPU and memory bound)."""

import asyncio

from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError

DUMMY_PASSWORD = "not-a-real-password"


class Argon2PasswordHasher:
    """PasswordHasher port over argon2-cffi (RFC 9106 low-memory profile)."""

    def __init__(self, hasher: Argon2 | None = None) -> None:
        """Use the default profile unless a cheaper one is passed (tests)."""
        self._hasher = hasher or Argon2()
        self._dummy: str | None = None

    async def hash(self, password: str) -> str:
        """Return the encoded Argon2id hash."""
        return await asyncio.to_thread(self._hasher.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        """Check a password; unknown accounts burn the same time."""
        if password_hash is None:
            if self._dummy is None:
                self._dummy = await self.hash(DUMMY_PASSWORD)
            await self._check(self._dummy, password)
            return False
        return await self._check(password_hash, password)

    async def _check(self, password_hash: str, password: str) -> bool:
        try:
            return bool(
                await asyncio.to_thread(self._hasher.verify, password_hash, password)
            )
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """True when the stored parameters differ from the current profile."""
        return self._hasher.check_needs_rehash(password_hash)
