"""Job `notebooks.purge_shared`: drop shared texts and cached results nobody uses."""

from datetime import timedelta

from app.modules.notebooks.domain.limits import (
    SHARED_CACHE_UNUSED_DAYS,
    SHARED_DOCUMENT_GRACE_HOURS,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

import structlog

BATCH = 500
MAX_BATCHES = 20
log = structlog.get_logger(__name__)


class PurgeShared:
    """Deletes documents no source points at and cache rows nobody has used (daily)."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> dict[str, int]:
        """Return how many `documents` and `cache` rows were removed.

        A document is kept for a day after it is created, so one that a source is
        about to point at is never taken away. Cached summaries and outputs go after
        90 days without a hit.
        """
        now = self.clock.now()
        grace = now - timedelta(hours=SHARED_DOCUMENT_GRACE_HOURS)
        documents = 0
        for _ in range(MAX_BATCHES):
            async with self.uow_factory() as uow:
                removed = await uow.documents.delete_unused(grace, BATCH)
                await uow.commit()
            documents += removed
            if removed < BATCH:
                break
        async with self.uow_factory() as uow:
            cache = await uow.shared.delete_stale(
                now - timedelta(days=SHARED_CACHE_UNUSED_DAYS)
            )
            await uow.commit()
        log.info("notebooks_shared_purged", documents=documents, cache=cache)
        return {"documents": documents, "cache": cache}
