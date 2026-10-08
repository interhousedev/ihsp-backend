"""Port: accept a Hydra login for a user (used by registration, B2)."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class LoginAcceptor(Protocol):
    """Creates a session and accepts the login challenge at Hydra."""

    async def accept(
        self,
        challenge: str,
        user_id: UUID,
        *,
        amr: Sequence[str],
        ip: str | None,
        user_agent: str | None,
        remember: bool,
    ) -> str:
        """Return the URL to send the browser to."""
        ...
