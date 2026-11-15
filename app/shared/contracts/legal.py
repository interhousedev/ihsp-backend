"""Legal consent: what identity needs from the legal module at registration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class LegalItem:
    """One accepted document: its kind and version number."""

    kind: str
    version: int


@dataclass(frozen=True, slots=True)
class ConsentDraft:
    """Acceptances to insert in the transaction that creates the account."""

    user_id: UUID
    items: tuple[LegalItem, ...]
    accepted_at: datetime
    ip: str | None
    user_agent: str | None


class LegalConsent(Protocol):
    """Read side: which versions a new user has to accept."""

    async def current_versions(self) -> dict[str, int]:
        """The current published version of every kind that has one."""
        ...


ConsentWriter = Callable[[AsyncSession, list[ConsentDraft]], Awaitable[None]]
"""Inserts the drafts on the caller's session (the caller commits)."""


@dataclass(frozen=True, slots=True)
class LegalHooks:
    """What identity is given: the read side and the writer for its transaction."""

    consent: LegalConsent
    writer: ConsentWriter
