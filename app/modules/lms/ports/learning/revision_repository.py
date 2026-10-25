"""Port: immutable step revisions."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import RevisionData


class RevisionRepository(Protocol):
    """Frozen step contents."""

    async def get(self, revision_id: UUID) -> RevisionData | None:
        """Return a revision with its parsed content."""
        ...

    async def get_many(self, revision_ids: Sequence[UUID]) -> dict[UUID, RevisionData]:
        """Return the revisions that exist, by id, in one query."""
        ...
