"""Port: one model call per shared document and language."""

from typing import Protocol
from uuid import UUID


class GuideLock(Protocol):
    """Keeps 30 students who open the same lesson file from paying 30 times."""

    async def try_claim(self, document_id: UUID, language: str) -> str | None:
        """Claim the right to write the guide; the token, or None when it is taken."""
        ...

    async def release(self, document_id: UUID, language: str, token: str) -> None:
        """Give the claim back (a claim also expires on its own)."""
        ...
