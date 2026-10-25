"""Job `notebooks.sweep_auto_notebooks` (cron): safety net for the auto sync."""

from app.modules.notebooks.domain.limits import (
    AUTO_ACTIVE_WITHIN,
    AUTO_SWEEP_AFTER,
    AUTO_SWEEP_BATCH,
)
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


class SweepAutoNotebooks:
    """Re-syncs notebooks whose lesson was changed without the links hook firing.

    Only notebooks opened within the last 30 days and not synced for an hour are
    touched, so idle notebooks cost nothing.
    """

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self) -> int:
        """Kick a sync for each due notebook (at most 200 per run); return how many."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            ids = await uow.notebooks.due_auto_sync(
                now - AUTO_SWEEP_AFTER, now - AUTO_ACTIVE_WITHIN, AUTO_SWEEP_BATCH
            )
        for notebook_id in ids:
            await self.kicker.kick(
                "notebooks.sync_auto_notebook", notebook_id=str(notebook_id)
            )
        return len(ids)
