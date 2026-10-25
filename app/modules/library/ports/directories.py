"""Ports to other modules' data that the library needs (adapters live in bootstrap)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SubjectView:
    """A subject with its name in the requested language."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class GroupView:
    """A study group as the reading-list editor lists it."""

    id: UUID
    name: str


class AcademicDirectory(Protocol):
    """Subjects, groups and cohorts from the academic module."""

    async def subject_names(
        self, subject_ids: Sequence[UUID], locale: str
    ) -> dict[UUID, str]:
        """Names of the existing subjects in the locale (unknown ids are absent)."""
        ...

    async def list_subjects(self, locale: str) -> list[SubjectView]:
        """All subjects, sorted by name."""
        ...

    async def student_group_id(self, user_id: UUID) -> UUID | None:
        """The active group of a student, or None."""
        ...

    async def student_cohort(self, user_id: UUID) -> str:
        """The year the student joined ("2025"), or an empty string when unknown."""
        ...

    async def teacher_teaches_subject(self, user_id: UUID, subject_id: UUID) -> bool:
        """True when the teacher has lessons of the subject in the current term."""
        ...

    async def group_user_ids(self, group_ids: Sequence[UUID]) -> list[UUID]:
        """Active students of the groups."""
        ...

    async def teacher_groups(self, user_id: UUID) -> list[GroupView]:
        """Active groups a teacher curates or has lessons with, sorted by name."""
        ...

    async def all_groups(self) -> list[GroupView]:
        """Every active group, sorted by name."""
        ...

    async def current_academic_year(self) -> str | None:
        """The academic year of the current term ("2026-2027"), or None."""
        ...
