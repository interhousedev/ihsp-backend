"""Port: the stored summary of the older turns of one chat thread."""

from typing import Protocol
from uuid import UUID

from app.modules.notebooks.domain.compaction import CompactSummary


class CompactStore(Protocol):
    """Summaries per notebook and student (Redis `nb:compact:{notebook}:{user}`)."""

    async def get(self, notebook_id: UUID, user_id: UUID) -> CompactSummary | None:
        """Return the stored summary, if any."""
        ...

    async def put(
        self, notebook_id: UUID, user_id: UUID, summary: CompactSummary
    ) -> None:
        """Store or replace the summary."""
        ...
