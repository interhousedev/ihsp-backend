"""Port: storage of onboarding progress."""

from typing import Protocol
from uuid import UUID

from app.modules.onboarding.domain.steps import Progress


class ProgressRepository(Protocol):
    """Progress rows, one per user."""

    async def get(self, user_id: UUID) -> Progress | None:
        """Return the row or None."""
        ...

    async def save(self, progress: Progress) -> None:
        """Insert or replace the user's row."""
        ...
