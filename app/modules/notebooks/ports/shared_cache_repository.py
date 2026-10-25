"""Port: shared caches of summaries and Studio outputs."""

from datetime import datetime
from typing import Protocol

from app.modules.notebooks.domain.entities import CachedArtifact, CachedSummary


class SharedCacheRepository(Protocol):
    """Rows in `notebooks.shared_summaries` and `notebooks.shared_artifacts`."""

    async def get_summary(
        self, selection_hash: str, language: str, now: datetime
    ) -> CachedSummary | None:
        """The summary kept for a set of texts; counts as a hit at `now`."""
        ...

    async def save_summary(
        self, selection_hash: str, language: str, summary: CachedSummary
    ) -> None:
        """Keep the summary (the first one stored for the key wins)."""
        ...

    async def get_artifact(
        self, cache_key: str, now: datetime
    ) -> CachedArtifact | None:
        """The output kept for a request; counts as a hit at `now`."""
        ...

    async def save_artifact(self, entry: CachedArtifact) -> None:
        """Keep the output (the first one stored for the key wins)."""
        ...

    async def delete_stale(self, unused_since: datetime) -> int:
        """Delete cache rows created and last hit before the cutoff."""
        ...
