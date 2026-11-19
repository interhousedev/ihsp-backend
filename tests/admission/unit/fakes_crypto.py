"""A cipher that does not encrypt, for tests of code that seals essay text."""

import hashlib
from uuid import UUID


class PlainCipher:
    """`EssayCipher` without encryption; `forget` makes old blobs unreadable."""

    def __init__(self) -> None:
        self.forgotten: list[UUID] = []
        self._generation: dict[UUID, int] = {}

    def _prefix(self, owner_id: UUID, record_id: UUID, column: str) -> bytes:
        gen = self._generation.get(owner_id, 0)
        return f"fake|{gen}|{owner_id}|{record_id}|{column}|".encode()

    async def seal(
        self, owner_id: UUID, record_id: UUID, column: str, text: str
    ) -> bytes:
        """The text behind a prefix bound to owner, record and column."""
        return self._prefix(owner_id, record_id, column) + text.encode()

    async def open(
        self, owner_id: UUID, record_id: UUID, column: str, blob: bytes
    ) -> str:
        """The text of a blob sealed for the same owner, record and column."""
        prefix = self._prefix(owner_id, record_id, column)
        if not blob.startswith(prefix):
            raise ValueError(
                "the blob was sealed for another record or a forgotten key"
            )
        return blob[len(prefix) :].decode()

    async def digest(self, owner_id: UUID, purpose: str, data: str) -> str:
        """A stable hex digest that changes when the owner's key is forgotten."""
        gen = self._generation.get(owner_id, 0)
        return hashlib.sha256(f"{gen}|{owner_id}|{purpose}|{data}".encode()).hexdigest()

    async def forget(self, owner_id: UUID) -> None:
        """Drop the owner's key: earlier blobs stop opening, new seals still work."""
        self.forgotten.append(owner_id)
        self._generation[owner_id] = self._generation.get(owner_id, 0) + 1
