"""In-memory unit of work of the onboarding module and its gateways."""

import copy
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.onboarding.domain.steps import Progress


class FakeOnboardingStore:
    """The "database": progress rows by user."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: dict[UUID, Progress] = {}


class _Progress:
    def __init__(self, store: FakeOnboardingStore) -> None:
        self._s = store

    async def get(self, user_id: UUID) -> Progress | None:
        found = self._s.rows.get(user_id)
        return copy.deepcopy(found) if found else None

    async def save(self, progress: Progress) -> None:
        self._s.rows[progress.user_id] = copy.deepcopy(progress)


class FakeOnboardingUow:
    """One transaction over a FakeOnboardingStore."""

    def __init__(self, store: FakeOnboardingStore) -> None:
        """Bind to the store."""
        self.progress = _Progress(store)

    async def __aenter__(self) -> Self:
        """Open."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Nothing to roll back."""

    async def commit(self) -> None:
        """Nothing to commit."""


class FakeImporter:
    """EmisCertificateImport that records who was refreshed."""

    def __init__(self) -> None:
        """Start with no calls."""
        self.calls: list[UUID] = []

    async def refresh(self, student_id: UUID) -> None:
        """Record the call."""
        self.calls.append(student_id)
