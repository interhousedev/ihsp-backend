"""Port: sign and read our own JWT-bearer assertions (RFC 7523)."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AssertionClaims:
    """What the token hook needs from a verified assertion."""

    user_id: UUID
    session_id: UUID
    amr: tuple[str, ...]


class AssertionSigner(Protocol):
    """Signs assertions for the mini app grant and verifies them in the hook."""

    def sign(self, user_id: UUID, session_id: UUID, amr: list[str]) -> str:
        """Return a signed assertion valid for 5 minutes."""
        ...

    def read(self, assertion: str) -> AssertionClaims | None:
        """Verify our signature and return the claims, or None if invalid."""
        ...
