"""Storage port of the non-lesson blocks."""

from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.day_blocks import DayBlock


class DayBlockStore(Protocol):
    """Reads and writes the blocks and finds a student's group."""

    async def list_all(self) -> list[DayBlock]:
        """Every block, ordered by start time and name."""
        ...

    async def get(self, block_id: UUID) -> DayBlock | None:
        """One block, None when missing."""
        ...

    async def save(self, block: DayBlock) -> None:
        """Insert or update the block."""
        ...

    async def delete(self, block_id: UUID) -> bool:
        """Delete the block; False when it did not exist."""
        ...

    async def student_group(self, user_id: UUID) -> tuple[UUID, int | None] | None:
        """(group id, course of the group) of a student, None without a group."""
        ...
