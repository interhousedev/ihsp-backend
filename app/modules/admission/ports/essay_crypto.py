"""Ports of essay encryption: per-student data keys and the field cipher.

Every student has one 256-bit data key. Essay text (bodies, titles, notes,
versions, ideas, stored reviews and the feedback invited readers leave) is
stored only as ciphertext sealed with that key. Destroying the key makes every
sealed field unreadable (crypto-shredding on erasure).
"""

from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

KEY_BYTES: Final = 32
"""Length of a data key (AES-256)."""


@dataclass(frozen=True, slots=True)
class EssayKey:
    """A student's data key; the secret never appears in a repr or a log."""

    owner_id: UUID
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Refuse a key of the wrong length."""
        if len(self.secret) != KEY_BYTES:
            raise ValueError("an essay key is 32 bytes")


class EssayKeyStore(Protocol):
    """Where the data keys live (Vault KV v2 in production)."""

    async def get(self, owner_id: UUID) -> EssayKey | None:
        """Return the student's key; None when it was never made or was destroyed."""
        ...

    async def create(self, owner_id: UUID) -> EssayKey:
        """Create the key once (check-and-set); after a lost race return the winner."""
        ...

    async def destroy(self, owner_id: UUID) -> None:
        """Delete the key with all its versions."""
        ...


class EssayCipher(Protocol):
    """Seals and opens essay text with the owner's data key."""

    async def seal(
        self, owner_id: UUID, record_id: UUID, column: str, text: str
    ) -> bytes:
        """Encrypt `text`; the owner, the record and the column are bound to it."""
        ...

    async def open(
        self, owner_id: UUID, record_id: UUID, column: str, blob: bytes
    ) -> str:
        """Decrypt a blob made by `seal` for the same owner, record and column."""
        ...

    async def digest(self, owner_id: UUID, purpose: str, data: str) -> str:
        """Return a keyed hex digest of `data` (HMAC-SHA256, a subkey per purpose).

        Used instead of a plain hash wherever a fingerprint of essay text is kept
        (cache keys, staleness), so nobody can test a guessed text against it and
        it becomes meaningless once the key is destroyed. Creates the key when
        missing, like `seal`.
        """
        ...

    async def forget(self, owner_id: UUID) -> None:
        """Destroy the owner's key and drop it from the caches (crypto-shredding)."""
        ...
