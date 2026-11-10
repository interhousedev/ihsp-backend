"""Port: persistence of personal API tokens."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.personal_token import PersonalToken


class PersonalTokenRepository(Protocol):
    """Reads and writes personal tokens."""

    async def add(self, token: PersonalToken) -> None:
        """Insert a token."""
        ...

    async def get(self, token_id: UUID) -> PersonalToken | None:
        """Return the token or None."""
        ...

    async def get_by_hash(self, token_hash: str) -> PersonalToken | None:
        """Find a token by the hash of its secret."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[PersonalToken]:
        """Tokens of a user, newest first."""
        ...

    async def save(self, token: PersonalToken) -> None:
        """Write every field of an existing token."""
        ...

    async def touch_last_used(
        self, token_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Set last_used_at unless it was updated within min_interval."""
        ...
