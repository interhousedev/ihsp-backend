"""Legal consent: what identity needs from the legal module at registration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

GLOBAL_APP = "global"
"""The scope of documents that apply to every app."""

APP_SCOPES = (
    GLOBAL_APP,
    "id",
    "sp",
    "staff",
    "admin",
    "lms",
    "library",
    "share",
    "landing",
    "admission",
)
"""Scopes a document may have: global or the name of one app."""

APP_HEADER = "X-IHSP-App"
"""Request header with the app that makes the call."""


def normalize_app(value: str | None) -> str:
    """The app scope of a request: a known app name, else ``global``."""
    name = (value or "").strip().lower()
    return name if name in APP_SCOPES else GLOBAL_APP


@dataclass(frozen=True, slots=True)
class LegalItem:
    """One accepted document: its kind, version number and app scope."""

    kind: str
    version: int
    app_scope: str = GLOBAL_APP


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


class ConsentGate(Protocol):
    """Refuses users who have not accepted the current documents."""

    async def execute(self, user_id: UUID, app: str = GLOBAL_APP) -> None:
        """Raise a ForbiddenError (legal/acceptance-required) while any is pending.

        Pending means the current global documents plus those of ``app``.
        """
        ...


ConsentWriter = Callable[[AsyncSession, list[ConsentDraft]], Awaitable[None]]
"""Inserts the drafts on the caller's session (the caller commits)."""


@dataclass(frozen=True, slots=True)
class LegalHooks:
    """What identity is given: the read side and the writer for its transaction."""

    consent: LegalConsent
    writer: ConsentWriter
