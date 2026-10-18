"""The student asks for a full EMIS sync from the settings page (idempotent).

A job already pending, running or succeeded is returned as it is and nothing is
queued again; a failed job is reset and queued once. The kick is best effort: the job
row is already pending, so the periodic retry job runs it if the kick is lost.
"""

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


class RequestStudentSync:
    """Queue (or report) the student's initial sync."""

    def __init__(
        self, *, jobs: StudentSyncJobs, kicker: TaskKicker, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self._jobs = jobs
        self._kicker = kicker
        self._clock = clock

    async def execute(self, actor: Actor) -> StudentSyncJob:
        """Return the job; ``status`` says whether it is queued, running or done."""
        actor.require(Role.STUDENT)
        job, queued = await self._jobs.request(actor.user_id, self._clock.now())
        if queued:
            try:
                await self._kicker.kick(TASK_NAME, user_id=str(actor.user_id))
            except Exception:
                log.warning(
                    "student_sync_manual_kick_failed", user_id=str(actor.user_id)
                )
        return job
