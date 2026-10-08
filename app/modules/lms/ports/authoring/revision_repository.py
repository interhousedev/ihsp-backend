"""Port: storage of immutable step revisions."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.modules.lms.domain.authoring.entities import StepRevision
from app.modules.lms.domain.authoring.enums import RevisionKind


class RevisionRepository(Protocol):
    """Reads and writes step revisions; a revision never changes once stored."""

    async def ensure(
        self,
        *,
        step_id: UUID,
        content: dict[str, Any],
        content_hash: str,
        kind: RevisionKind,
        label: str | None,
        file_ids: Sequence[UUID],
        created_by: UUID,
        now: datetime,
    ) -> StepRevision:
        """Insert a revision or reuse the one with the same hash (updating a label)."""
        ...

    async def get(self, revision_id: UUID) -> StepRevision | None:
        """Return the revision, or None."""
        ...

    async def get_many(self, revision_ids: Sequence[UUID]) -> dict[UUID, StepRevision]:
        """Return the revisions that exist, by ID."""
        ...

    async def list_for_history(self, step_id: UUID, limit: int) -> list[StepRevision]:
        """Return published and checkpoint revisions of a step, newest first."""
        ...

    async def known_ids(self, step_id: UUID) -> set[str]:
        """Return every block, question, option and card ID in any revision."""
        ...

    async def mark_published(self, revision_ids: Sequence[UUID], now: datetime) -> None:
        """Set `published_at` where it is still empty."""
        ...

    async def prune_checkpoints(
        self,
        *,
        keep: int,
        step_id: UUID | None = None,
        protect: Sequence[UUID] = (),
    ) -> int:
        """Delete checkpoints beyond the newest `keep` per step; return the count.

        Revisions that were published, are used by attempts or are listed in
        `protect` are never deleted.
        """
        ...

    async def prune_previews(self, *, older_than: datetime) -> int:
        """Delete old preview revisions that were not published or attempted."""
        ...
