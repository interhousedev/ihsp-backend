"""Port: immutable step revisions."""

from typing import Protocol
from uuid import UUID

from app.modules.lms.domain.learning.entities import RevisionData


class RevisionRepository(Protocol):
    """Frozen step contents."""

    async def get(self, revision_id: UUID) -> RevisionData | None:
        """Return a revision with its parsed content."""
        ...
