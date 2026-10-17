"""Port: students, groups and curators (provider: academic via the composition root)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class StudentInfo:
    """An active student with the group they study in."""

    id: UUID
    name: str
    group_id: UUID
    group_name: str
    subgroup: str | None


@dataclass(frozen=True, slots=True)
class GroupInfo:
    """A group and the subgroups its students are split into."""

    id: UUID
    name: str
    subgroups: tuple[str, ...]


class StudentDirectory(Protocol):
    """Who studies where, and who curates which groups."""

    async def student(self, user_id: UUID) -> StudentInfo | None:
        """Return the active student or None."""
        ...

    async def students(
        self,
        group_ids: Sequence[UUID] | None,
        *,
        subgroup: str | None = None,
        query: str | None = None,
    ) -> list[StudentInfo]:
        """Return active students of the groups (None: every group), by name.

        ``query`` matches the name by words, case-insensitively.
        """
        ...

    async def groups(self, group_ids: Sequence[UUID] | None) -> list[GroupInfo]:
        """Return active groups by name with their subgroups; None means all."""
        ...

    async def curated_group_ids(self, teacher_id: UUID) -> list[UUID]:
        """Return ids of the groups the teacher curates."""
        ...
