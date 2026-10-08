"""Storage of student import previews (Redis ``import:{id}`` for one hour)."""

from typing import Any, Protocol
from uuid import UUID


class ImportStore(Protocol):
    """Keeps a parsed preview between upload and confirmation."""

    async def save(self, import_id: UUID, payload: dict[str, Any]) -> None:
        """Store the preview for an hour."""
        ...

    async def load(self, import_id: UUID) -> dict[str, Any] | None:
        """Return the preview or None if it expired."""
        ...

    async def delete(self, import_id: UUID) -> None:
        """Forget the preview."""
        ...
