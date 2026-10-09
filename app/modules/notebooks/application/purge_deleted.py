"""Job `notebooks.purge_deleted`: remove notebooks deleted a week ago (§ 3.2.7)."""

from datetime import timedelta

from app.modules.notebooks.domain.limits import DELETED_RETENTION_DAYS
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

import structlog

BATCH = 100
log = structlog.get_logger(__name__)


class PurgeDeleted:
    """Hard-deletes notebooks soft-deleted more than 7 days ago (cron 04:15)."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> int:
        """Delete the due notebooks (sources, messages and outputs go with them).

        Works in batches of 100, one transaction each, and returns how many
        notebooks were removed. Running it again finds nothing more to do.
        """
        cutoff = self.clock.now() - timedelta(days=DELETED_RETENTION_DAYS)
        total = 0
        while True:
            async with self.uow_factory() as uow:
                ids = await uow.notebooks.deleted_before(cutoff, BATCH)
                removed = await uow.notebooks.hard_delete(ids)
                await uow.commit()
            total += removed
            if removed == 0 or len(ids) < BATCH:
                break
        log.info("notebooks_purged", count=total)
        return total
