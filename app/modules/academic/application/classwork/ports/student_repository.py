"""Port: students and the groups they belong to."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.academic.domain.classwork.records import StudentRecord


class StudentRepository(Protocol):
    """Read access to ``academic.students``."""

    async def get(self, user_id: UUID) -> StudentRecord | None:
        """Return the student or None."""
        ...

    async def active_in_groups(self, group_ids: Sequence[UUID]) -> list[StudentRecord]:
        """Return the active students of the groups."""
        ...

    async def by_ids(self, user_ids: Sequence[UUID]) -> list[StudentRecord]:
        """Return the students with these ids, whatever their status."""
        ...
