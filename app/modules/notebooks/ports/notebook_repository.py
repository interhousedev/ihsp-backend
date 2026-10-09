"""Port: storage of notebooks."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.entities import Notebook
from app.modules.notebooks.domain.enums import NotebookOrigin


@dataclass(frozen=True, slots=True)
class NotebookCursor:
    """Position in the list: pinned first, then last opened (nulls last), then id."""

    pinned: bool
    last_opened_at: datetime | None
    id: UUID


class NotebookRepository(Protocol):
    """Notebooks in `notebooks.notebooks`."""

    async def add(self, notebook: Notebook) -> None:
        """Insert a new notebook."""
        ...

    async def get(self, notebook_id: UUID) -> Notebook | None:
        """Return the notebook (deleted or not) with its source counts."""
        ...

    async def get_for_update(self, notebook_id: UUID) -> Notebook | None:
        """Return the notebook and lock its row until the transaction ends."""
        ...

    async def save(self, notebook: Notebook) -> None:
        """Write the notebook's stored fields."""
        ...

    async def count_live(self, owner_id: UUID) -> int:
        """Return how many non-deleted notebooks the owner wrote themselves."""
        ...

    async def count_live_auto(self, owner_id: UUID) -> int:
        """Return how many non-deleted subject and lesson notebooks the owner has."""
        ...

    async def find_auto(
        self, owner_id: UUID, origin: NotebookOrigin, target_id: UUID
    ) -> Notebook | None:
        """The owner's live subject notebook (`target_id` = subject) or lesson one."""
        ...

    async def add_auto(self, notebook: Notebook) -> bool:
        """Insert an auto notebook; False when the owner already has a live one."""
        ...

    async def add_workspace(self, notebook: Notebook) -> bool:
        """Insert a course workspace; False when the course already has a live one."""
        ...

    async def get_by_course(self, course_id: UUID) -> Notebook | None:
        """Return the live workspace of an LMS course, if it has one."""
        ...

    async def auto_ids_for_lesson(
        self, subject_id: UUID, lesson_id: UUID, limit: int
    ) -> list[UUID]:
        """Live notebooks that feed on a lesson: its subject's and its own."""
        ...

    async def due_auto_sync(
        self, synced_before: datetime, opened_after: datetime, limit: int
    ) -> list[UUID]:
        """Live auto notebooks opened lately and not synced since the cutoff."""
        ...

    async def list_for_owner(
        self,
        owner_id: UUID,
        *,
        query: str | None,
        after: NotebookCursor | None,
        limit: int,
    ) -> list[Notebook]:
        """Live notebooks: pinned first, then `last_opened_at` desc (nulls last).

        `query` filters by title (case-insensitive substring). Course workspaces are
        not listed.
        """
        ...

    async def due_summaries(self, now: datetime, limit: int) -> list[Notebook]:
        """Notebooks with `summary_status='stale'` and `summary_due_at <= now`.

        Rows are locked with `FOR UPDATE SKIP LOCKED` until the transaction ends.
        """
        ...

    async def stuck_summaries(
        self, updated_before: datetime, limit: int
    ) -> list[Notebook]:
        """Live notebooks with `summary_status='building'` not updated since the cutoff.

        Rows are locked with `FOR UPDATE SKIP LOCKED` until the transaction ends.
        """
        ...

    async def deleted_before(self, cutoff: datetime, limit: int) -> list[UUID]:
        """Ids of notebooks soft-deleted before the cutoff."""
        ...

    async def ids_for_owner(self, owner_id: UUID) -> list[UUID]:
        """Ids of the owner's notebooks, deleted or not (not course workspaces)."""
        ...

    async def hard_delete(self, notebook_ids: Sequence[UUID]) -> int:
        """Delete notebooks; sources, passages, messages and outputs cascade."""
        ...
