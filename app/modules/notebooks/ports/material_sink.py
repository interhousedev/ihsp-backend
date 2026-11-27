"""Ports of the material sink."""

from typing import Any, Protocol
from uuid import UUID


class NotebookDirectory(Protocol):
    """Finds or creates a teacher's subject notebook."""

    async def subject_notebook(
        self, owner_id: UUID, subject_id: UUID, group_id: UUID | None
    ) -> UUID:
        """The notebook of the subject, or of the subject in one group."""
        ...


class SourceWriter(Protocol):
    """Writes text sources."""

    async def add_text(
        self,
        *,
        notebook_id: UUID,
        owner_id: UUID,
        title: str,
        body_md: str,
        ref: dict[str, Any],
        ref_key: str,
        origin: dict[str, Any],
    ) -> Any:
        """Add a text source; idempotent on (notebook_id, ref_key)."""
        ...
