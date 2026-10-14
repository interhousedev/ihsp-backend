"""The calling student's last full EMIS sync (the settings page polls it)."""

from app.modules.academic.application.schedule.student_sync_state import (
    SyncState,
    SyncStateStore,
)
from app.shared.actor import Actor, Role


class GetStudentSync:
    """Read the state the request and the worker wrote."""

    def __init__(self, *, state: SyncStateStore) -> None:
        """Store the state store."""
        self._state = state

    async def execute(self, actor: Actor) -> SyncState | None:
        """None before the first sync."""
        actor.require(Role.STUDENT)
        return await self._state.get(actor.user_id)
