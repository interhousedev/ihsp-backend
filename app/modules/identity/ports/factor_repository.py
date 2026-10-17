"""Port: TOTP state and passkeys of users."""

from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.factors import Passkey, UserFactors


class FactorRepository(Protocol):
    """Rows of id.user_factors and id.passkeys."""

    async def get(self, user_id: UUID) -> UserFactors | None:
        """The factors of the user, if any were ever stored."""
        ...

    async def save(self, factors: UserFactors) -> None:
        """Insert or replace the factors of the user."""
        ...

    async def list_passkeys(self, user_id: UUID) -> list[Passkey]:
        """The passkeys of the user, oldest first."""
        ...

    async def get_passkey(self, passkey_id: UUID) -> Passkey | None:
        """One passkey by id."""
        ...

    async def get_passkey_by_credential(self, credential_id: bytes) -> Passkey | None:
        """One passkey by its WebAuthn credential id."""
        ...

    async def add_passkey(self, passkey: Passkey) -> None:
        """Insert a passkey."""
        ...

    async def save_passkey(self, passkey: Passkey) -> None:
        """Update name, sign count and last use."""
        ...

    async def delete_passkey(self, passkey_id: UUID) -> None:
        """Remove a passkey."""
        ...
