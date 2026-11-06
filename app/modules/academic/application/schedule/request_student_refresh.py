"""The student refreshes their own EMIS data, at most once per cooldown (A1, D5).

`RequestStudentSync` returns a succeeded job unchanged, so it cannot refresh. This one
uses the administrators' durable path: the worker's claim, the EMIS global pause and
the rate limiter all apply.
"""

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.modules.academic.application.schedule.run_student_sync import TASK_NAME
from app.modules.academic.application.schedule.student_sync_jobs import (
    StudentSyncJob,
    StudentSyncJobs,
)
from app.shared.actor import Actor, Role
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)


class SyncCooldown(Protocol):
    """Who refreshed recently."""

    async def take(self, user_id: UUID, seconds: int) -> int:
        """Start the cooldown and return 0, or return the seconds still to wait."""
        ...


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """What the request did."""

    status: Literal["queued", "running", "cooldown"]
    job: StudentSyncJob | None
    retry_after_seconds: int = 0


class RequestStudentRefresh:
    """Queue a refresh of the actor's own data."""

    def __init__(
        self,
        *,
        jobs: StudentSyncJobs,
        kicker: TaskKicker,
        clock: Clock,
        cooldown: SyncCooldown,
        cooldown_seconds: int,
    ) -> None:
        """Store the collaborators and the length of the cooldown."""
        self._jobs = jobs
        self._kicker = kicker
        self._clock = clock
        self._cooldown = cooldown
        self._seconds = cooldown_seconds

    async def execute(self, actor: Actor) -> RefreshOutcome:
        """Return the job; a pending or running one is returned without a new cost."""
        actor.require(Role.STUDENT)
        user_id = actor.user_id
        job = await self._jobs.get(user_id)
        if job is not None and job.status in ("pending", "running"):
            return RefreshOutcome("running", job)
        wait = await self._cooldown.take(user_id, self._seconds)
        if wait:
            return RefreshOutcome("cooldown", job, wait)
        job, queued = await self._jobs.request_refresh(user_id, self._clock.now())
        if queued:
            try:
                await self._kicker.kick(TASK_NAME, user_id=str(user_id))
            except Exception:  # the job row is durable: the periodic retry runs it
                log.warning("student_refresh_kick_failed", user_id=str(user_id))
        return RefreshOutcome("queued" if queued else "running", job)


def sync_error_code(raw: str | None) -> str | None:
    """A job's last error as a fixed code; raw text never leaves the backend."""
    if raw is None:
        return None
    text = raw.lower()
    if "auth" in text:
        return "emis_reauth_required"
    if "emis" in text:
        return "emis_unavailable"
    if text.startswith("stopped"):
        return "stopped"
    return "sync_failed"
