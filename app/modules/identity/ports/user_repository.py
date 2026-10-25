"""Port: persistence of users."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.identity.domain.user import User
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.pagination import Page


class UserRepository(Protocol):
    """Reads and writes users."""

    async def get(self, user_id: UUID) -> User | None:
        """Return the user or None."""
        ...

    async def get_many(self, user_ids: Sequence[UUID]) -> dict[UUID, User]:
        """Return the existing users among the ids."""
        ...

    async def get_by_login(self, login: str) -> User | None:
        """Find a user by login, case-insensitively."""
        ...

    async def get_by_recovery_email(self, email: str) -> User | None:
        """Find a user by recovery email, case-insensitively."""
        ...

    async def get_by_emis_teacher_id(self, emis_teacher_id: int) -> User | None:
        """Find the teacher linked to an EMIS teacher id."""
        ...

    async def list_with_roles(self, roles: Sequence[Role]) -> list[User]:
        """Return users holding any role, except deleted and deactivated ones."""
        ...

    async def get_by_activation_hash(self, token_hash: str) -> User | None:
        """Find the user holding an activation token hash."""
        ...

    async def get_by_otp_reset_request(self, request_id: UUID) -> User | None:
        """Find the user with a pending OTP reset request."""
        ...

    async def add(self, user: User) -> None:
        """Insert a new user."""
        ...

    async def save(self, user: User) -> None:
        """Write every field of an existing user."""
        ...

    async def logins_with_prefix(self, prefix: str) -> set[str]:
        """Return the existing logins starting with the prefix (any case)."""
        ...

    async def email_taken(
        self, email: str, *, except_user_id: UUID | None = None
    ) -> bool:
        """True when another user's recovery email equals the email."""
        ...

    async def ids_with_roles(self, roles: Sequence[Role]) -> list[UUID]:
        """Return ids of active users holding any of the roles."""
        ...

    async def search(
        self,
        *,
        query: str | None,
        roles: Sequence[Role],
        status: UserStatus | None,
        cursor: str | None,
        limit: int,
    ) -> Page[User]:
        """Administration list: filter by text, role and status, newest first."""
        ...

    async def search_active(
        self, query: str, *, roles: Sequence[Role], limit: int
    ) -> list[User]:
        """Directory search among active users by name or login."""
        ...

    async def due_otp_resets(self, now: datetime) -> list[User]:
        """Users whose OTP reset is due."""
        ...

    async def purgeable(self, deleted_before: datetime, limit: int) -> list[User]:
        """Deleted users whose personal data has not been removed yet."""
        ...

    async def merge_preferences(
        self, user_id: UUID, patch: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically merge a JSON patch into preferences; return the result."""
        ...

    async def get_epoch(self, user_id: UUID) -> int | None:
        """Return the user's auth epoch, or None if the user does not exist."""
        ...
