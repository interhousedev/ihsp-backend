"""Port: persistence of login sessions."""

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.session import LoginSession


class SessionRepository(Protocol):
    """Reads and writes login sessions."""

    async def add(self, session: LoginSession) -> None:
        """Insert a session."""
        ...

    async def save(self, session: LoginSession) -> None:
        """Write every field of an existing session."""
        ...

    async def get(self, session_id: UUID) -> LoginSession | None:
        """Return the session or None."""
        ...

    async def get_by_hydra_sid(self, hydra_sid: str) -> LoginSession | None:
        """Return the session that belongs to a Hydra login session."""
        ...

    async def list_active(self, user_id: UUID, now: datetime) -> list[LoginSession]:
        """Active sessions of a user, most recently seen first."""
        ...

    async def latest_active(self, user_id: UUID, now: datetime) -> LoginSession | None:
        """The most recently created active session of a user."""
        ...

    async def revoke(self, session_id: UUID, now: datetime) -> LoginSession | None:
        """Revoke one active session; return it, or None if it was not active."""
        ...

    async def revoke_all(
        self, user_id: UUID, now: datetime, *, except_id: UUID | None = None
    ) -> list[LoginSession]:
        """Revoke every active session of a user (except one); return them."""
        ...

    async def touch(
        self, session_id: UUID, now: datetime, *, min_interval: timedelta
    ) -> None:
        """Set last_seen_at unless it was updated within min_interval."""
        ...
