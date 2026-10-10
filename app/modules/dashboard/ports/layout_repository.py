"""Port: storage of dashboard layouts."""

from typing import Protocol
from uuid import UUID

from app.modules.dashboard.domain.layout import Layout


class LayoutRepository(Protocol):
    """One layout per user."""

    async def get(self, user_id: UUID, *, for_update: bool = False) -> Layout | None:
        """Return the stored layout, or None if the user never saved one."""
        ...

    async def save(self, layout: Layout) -> None:
        """Insert or replace the layout."""
        ...
