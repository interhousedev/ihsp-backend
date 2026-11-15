"""Contracts between identity and privacy (account erasure on request).

Identity asks privacy to record an erasure request after the password and the
one-time code were checked (``ErasureGateway``). Privacy starts the deletion and
sends the notices through identity (``AccountControl``).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus


@dataclass(frozen=True, slots=True)
class ErasureTicket:
    """The recorded request."""

    request_id: UUID
    status: str


@dataclass(frozen=True, slots=True)
class AccountInfo:
    """What the admin list shows about the requester."""

    user_id: UUID
    name: str
    login: str | None
    roles: frozenset[Role]
    status: UserStatus


class ErasureGateway(Protocol):
    """Implemented by privacy, used by identity."""

    async def request(
        self, user_id: UUID, *, ip: str | None, user_agent: str | None
    ) -> ErasureTicket:
        """Record a ``pending_review`` request; idempotent while one is open."""
        ...

    async def complete(self, user_id: UUID) -> None:
        """The deletion window ran out and the data was removed."""
        ...

    async def restored(self, user_id: UUID) -> None:
        """The user restored the account in the window: cancel the request."""
        ...


class AccountControl(Protocol):
    """Implemented by identity, used by privacy."""

    async def start_deletion(
        self, user_id: UUID, *, approved_by: UUID, ip: str | None
    ) -> date:
        """Begin the 30-day window (``pending_deletion``); return the purge date."""
        ...

    async def send_notice(
        self, user_id: UUID, text_key: str, params: dict[str, Any]
    ) -> None:
        """Email the recovery address in the user's locale (best effort)."""
        ...

    async def describe(self, user_ids: Sequence[UUID]) -> dict[UUID, AccountInfo]:
        """Name, login, roles and status of the accounts."""
        ...
