"""Port: the admission consent purposes a user has granted (provider: legal)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

STAFF_VIEW: Final = "admission_staff_view"
AI: Final = "admission_ai"
SHARING: Final = "admission_sharing"
FINANCE: Final = "admission_finance"
PURPOSES: Final = (STAFF_VIEW, AI, SHARING, FINANCE)


class PurposeConsents(Protocol):
    """Which purposes each user has consented to (current versions only)."""

    async def granted(self, user_ids: Sequence[UUID]) -> dict[UUID, frozenset[str]]:
        """Return the granted purposes per user; users without any are absent."""
        ...


class NoPurposeConsents:
    """Used until legal provides purposes: nothing is granted."""

    async def granted(self, user_ids: Sequence[UUID]) -> dict[UUID, frozenset[str]]:
        """Return no grants."""
        return {}


@dataclass(frozen=True, slots=True)
class PurposeGrant:
    """One purpose consent of a user, current or withdrawn."""

    purpose: str
    method: str
    given_at: dt.datetime
    withdrawn_at: dt.datetime | None = None

    @property
    def active(self) -> bool:
        """Return whether the consent is in force."""
        return self.withdrawn_at is None


class PurposeConsentStore(PurposeConsents, Protocol):
    """Purpose consents that the subject can also grant and withdraw."""

    async def grants_of(self, user_id: UUID) -> list[PurposeGrant]:
        """Return the latest grant of every purpose the user ever answered."""
        ...

    async def grant(
        self, user_id: UUID, purpose: str, *, now: dt.datetime, method: str = "app"
    ) -> PurposeGrant:
        """Record a consent; an already granted purpose is returned unchanged."""
        ...

    async def withdraw(self, user_id: UUID, purpose: str, *, now: dt.datetime) -> bool:
        """Withdraw a consent; return whether one was in force."""
        ...


class MemoryPurposeConsents:
    """In-process store; the default until legal's SQL store is wired, and tests."""

    def __init__(self) -> None:
        """Start without any answer."""
        self._rows: dict[tuple[UUID, str], PurposeGrant] = {}

    async def granted(self, user_ids: Sequence[UUID]) -> dict[UUID, frozenset[str]]:
        """Return the purposes in force per user."""
        out: dict[UUID, set[str]] = {}
        for (user_id, purpose), row in self._rows.items():
            if user_id in user_ids and row.active:
                out.setdefault(user_id, set()).add(purpose)
        return {u: frozenset(p) for u, p in out.items()}

    async def grants_of(self, user_id: UUID) -> list[PurposeGrant]:
        """Return the stored answers of the user."""
        return [r for (u, _), r in self._rows.items() if u == user_id]

    async def grant(
        self, user_id: UUID, purpose: str, *, now: dt.datetime, method: str = "app"
    ) -> PurposeGrant:
        """Record the consent unless one is already in force."""
        current = self._rows.get((user_id, purpose))
        if current is not None and current.active:
            return current
        row = PurposeGrant(purpose, method, now)
        self._rows[(user_id, purpose)] = row
        return row

    async def withdraw(self, user_id: UUID, purpose: str, *, now: dt.datetime) -> bool:
        """Mark the consent withdrawn."""
        current = self._rows.get((user_id, purpose))
        if current is None or not current.active:
            return False
        self._rows[(user_id, purpose)] = PurposeGrant(
            purpose, current.method, current.given_at, now
        )
        return True
