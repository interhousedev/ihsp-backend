"""Run again a sync that EMIS paused, once the pause is over (periodic, every 5 min)."""

from app.modules.academic.application.marks.ports.sync_control import SyncControl
from app.modules.academic.application.marks.sync_all import SyncAll
from app.modules.academic.domain.marks.errors import SyncAlreadyRunningError


class ResumePausedSync:
    """Kick the paused run's slot again when EMIS may be called; else keep waiting."""

    def __init__(self, *, control: SyncControl, sync_all: SyncAll) -> None:
        """Store the control flags and the sync use case."""
        self._control = control
        self._sync_all = sync_all

    async def execute(self) -> bool:
        """True when a paused run was started again."""
        if await self._control.emis_pause_seconds() > 0:
            return False
        slot = await self._control.take_resume()
        if slot is None:
            return False
        try:
            await self._sync_all.execute(slot)
        except SyncAlreadyRunningError:
            await self._control.set_resume(slot)
            return False
        return True
