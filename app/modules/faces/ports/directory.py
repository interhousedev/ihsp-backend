"""Port: students, their groups and curators (academic and identity)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StudentInfo:
    """A student as the entrance shows them."""

    user_id: UUID
    full_name: str
    group_id: UUID
    group_name: str


class StudentDirectory(Protocol):
    """Reads students and curators through the academic and identity contracts."""

    async def student(self, user_id: UUID) -> StudentInfo | None:
        """Return the student or None when the user is not a student."""
        ...

    async def curates(self, teacher_id: UUID, group_id: UUID) -> bool:
        """Return True when the teacher is a curator of the group."""
        ...

    async def full_names(self, user_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Return the full names of the users that exist."""
        ...
