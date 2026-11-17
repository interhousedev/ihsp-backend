"""Port: the memory notes of a student."""

from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.memory_notes import MemoryNote


class MemoryNoteRepository(Protocol):
    """Memory notes, newest first."""

    async def list_for(self, student_id: UUID) -> list[MemoryNote]:
        """Return the student's notes, newest first."""
        ...

    async def count_for(self, student_id: UUID) -> int:
        """Return how many notes the student has."""
        ...

    async def get(self, note_id: UUID) -> MemoryNote | None:
        """Return one note."""
        ...

    async def add(self, note: MemoryNote) -> None:
        """Insert a note."""
        ...

    async def delete(self, note_id: UUID) -> None:
        """Delete a note."""
        ...
