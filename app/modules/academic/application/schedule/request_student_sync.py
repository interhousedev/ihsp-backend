"""The student asks for a full EMIS sync from the settings (once per ten minutes)."""

from app.modules.academic.application.schedule.student_sync_state import (
    SYNC_WINDOW_SECONDS,
    SyncState,
    SyncStateStore,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import RateLimitedError
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker


class RequestStudentSync:
    """Queue `academic.sync_student_all` for the calling student."""

    def __init__(
        self, *, state: SyncStateStore, kicker: TaskKicker, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self._state = state
        self._kicker = kicker
        self._clock = clock

    async def execute(self, actor: Actor) -> SyncState:
        """Return the queued state; RateLimitedError inside the window."""
        actor.require(Role.STUDENT)
        left = await self._state.claim(actor.user_id, seconds=SYNC_WINDOW_SECONDS)
        if left is not None:
            raise RateLimitedError(params={"retry_after": left})
        state = SyncState("queued", requested_at=self._clock.now())
        await self._state.put(actor.user_id, state)
        await self._kicker.kick(
            "academic.sync_student_all", user_id=str(actor.user_id), with_marks=True
        )
        return state
