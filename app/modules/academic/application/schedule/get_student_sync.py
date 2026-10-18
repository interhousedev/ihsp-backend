"""The calling student's initial sync job (the settings page polls it)."""

from app.modules.academic.application.schedule.student_sync_jobs import (
    StudentSyncJob,
    StudentSyncJobs,
)
from app.shared.actor import Actor, Role


class GetStudentSync:
    """Read the durable sync record."""

    def __init__(self, *, jobs: StudentSyncJobs) -> None:
        """Store the job port."""
        self._jobs = jobs

    async def execute(self, actor: Actor) -> StudentSyncJob | None:
        """None when the student has no job (no registration through EMIS)."""
        actor.require(Role.STUDENT)
        return await self._jobs.get(actor.user_id)
