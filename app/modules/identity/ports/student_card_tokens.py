"""Where the permanent QR tokens of student cards live."""

from typing import Protocol
from uuid import UUID


class StudentCardTokens(Protocol):
    """One QR token per student; replacing it revokes the old one."""

    async def ensure(self, user_id: UUID, candidate: str) -> str:
        """Return the student's token, storing `candidate` when there is none."""
        ...

    async def replace(self, user_id: UUID, token: str) -> None:
        """Store a new token for the student; the old one stops working."""
        ...

    async def owner(self, token: str) -> UUID | None:
        """Return the student behind a token, None when it is unknown."""
        ...
