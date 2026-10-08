"""Restart processing of files that have been in 'processing' too long."""

from app.modules.files.application.process_hook import PROCESS_TASK
from app.modules.files.domain.policy import PROCESSING_STALE_AFTER
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

SWEEP_LIMIT = 200


class SweepProcessing:
    """Every 10 minutes: re-kick ``files.process`` for stuck rows."""

    def __init__(
        self, *, uow_factory: UowFactory, kicker: TaskKicker, clock: Clock
    ) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._kicker = kicker
        self._clock = clock

    async def execute(self) -> int:
        """Kick the task for each stale row; return how many were kicked."""
        cutoff = self._clock.now() - PROCESSING_STALE_AFTER
        async with self._uow_factory() as uow:
            stale = await uow.files.list_stale_processing(cutoff, SWEEP_LIMIT)
        for file in stale:
            await self._kicker.kick(PROCESS_TASK, file_id=str(file.id))
        return len(stale)
