"""Ports of the essays slice: storage and a read view for other slices."""

import datetime as dt
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.essays import Essay, EssayIdea, EssayVersion


class EssayRepository(Protocol):
    """Essays, their versions and the ideas board."""

    async def list_for(
        self, student_id: UUID, *, include_unreadable: bool = False
    ) -> list[Essay]:
        """Return the student's essays, newest edit first.

        Essays whose sealed text no longer opens are skipped, or returned as
        text-less stubs with `unreadable` set when `include_unreadable`.
        """
        ...

    async def owner_of(self, essay_id: UUID) -> UUID | None:
        """Return the owner of an essay without opening its text."""
        ...

    async def statuses(self, student_id: UUID) -> list[str]:
        """Return the status of each essay without opening the sealed text."""
        ...

    async def get(self, essay_id: UUID) -> Essay | None:
        """Return one essay."""
        ...

    async def add(self, essay: Essay) -> Essay:
        """Insert an essay."""
        ...

    async def update(self, essay: Essay) -> Essay:
        """Store the essay; raises AdmissionConflictError on a stale lock_version."""
        ...

    async def delete(self, essay_id: UUID) -> None:
        """Delete the essay with its versions."""
        ...

    async def versions(self, essay_id: UUID) -> list[EssayVersion]:
        """Return the versions, newest first."""
        ...

    async def version(self, essay_id: UUID, version: int) -> EssayVersion | None:
        """Return one version."""
        ...

    async def add_version(self, version: EssayVersion) -> EssayVersion:
        """Insert a version."""
        ...

    async def set_shared(
        self, essay_id: UUID, version: int, shared: bool
    ) -> EssayVersion | None:
        """Share or unshare one version with staff."""
        ...

    async def ideas_for(self, student_id: UUID) -> list[EssayIdea]:
        """Return the ideas board in display order."""
        ...

    async def get_idea(self, idea_id: UUID) -> EssayIdea | None:
        """Return one idea."""
        ...

    async def add_idea(self, idea: EssayIdea) -> EssayIdea:
        """Insert an idea."""
        ...

    async def update_idea(self, idea: EssayIdea) -> EssayIdea:
        """Store the idea (compare-and-set on lock_version)."""
        ...

    async def delete_idea(self, idea_id: UUID) -> None:
        """Delete an idea."""
        ...


@dataclass(frozen=True, slots=True)
class EssayText:
    """The text of one essay as other slices read it."""

    essay_id: UUID
    student_id: UUID
    kind: str
    title: str
    prompt_text: str
    word_limit: int | None
    list_entry_id: UUID | None
    body: str
    word_count: int
    updated_at: dt.datetime


class EssayReader(Protocol):
    """Read the latest essay texts of a student."""

    async def latest_for(
        self, student_id: UUID, *, shared_only: bool = False
    ) -> list[EssayText]:
        """Return the live drafts, or the latest shared version of each essay."""
        ...
