"""Delete notifications older than 90 days (task notify.purge_old)."""

from collections.abc import Callable
from datetime import timedelta

from app.modules.notify.ports.unit_of_work import NotifyUnitOfWork
from app.shared.clock import Clock

import structlog

log = structlog.get_logger(__name__)

RETENTION = timedelta(days=90)


class PurgeOld:
    """Removes notifications past the retention period."""

    def __init__(
        self, *, uow_factory: Callable[[], NotifyUnitOfWork], clock: Clock
    ) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(self) -> int:
        """Delete old rows and return how many were removed."""
        cutoff = self.clock.now() - RETENTION
        async with self.uow_factory() as uow:
            deleted = await uow.notifications.purge_created_before(cutoff)
            await uow.commit()
        log.info("notifications_purged", deleted=deleted)
        return deleted
