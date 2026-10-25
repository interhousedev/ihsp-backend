"""Administrator stops: a running sync run or one running student sync (SYNC-STOP)."""

from uuid import UUID

from app.modules.academic.application.marks.ports.sync_control import SyncControl
from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.application.schedule.student_sync_jobs import StudentSyncJobs
from app.modules.academic.domain.marks.errors import (
    SyncNotRunningError,
    SyncRunNotFoundError,
)
from app.shared.actor import Actor, Role


class StopSyncRun:
    """Ask a running sync run to stop; it ends ``stopped`` after students in flight."""

    def __init__(self, *, uow_factory: MarksUowFactory, control: SyncControl) -> None:
        """Store the unit of work factory and the control flags."""
        self._uow_factory = uow_factory
        self._control = control

    async def execute(self, actor: Actor, run_id: UUID) -> None:
        """Admins only; 404 for an unknown run, 409 when it is not running."""
        actor.require(Role.ADMIN)
        async with self._uow_factory() as uow:
            status = await uow.sync_runs.status_of(run_id)
        if status is None:
            raise SyncRunNotFoundError(support_details=f"run {run_id}")
        if status != "running":
            raise SyncNotRunningError(support_details=f"run is {status}")
        await self._control.request_run_stop(run_id)


class StopStudentSync:
    """Ask a running student sync to stop before its next step."""

    def __init__(self, *, jobs: StudentSyncJobs, control: SyncControl) -> None:
        """Store the job port and the control flags."""
        self._jobs = jobs
        self._control = control

    async def execute(self, actor: Actor, user_id: UUID) -> None:
        """Admins only; 409 when the student's sync is not running."""
        actor.require(Role.ADMIN)
        job = await self._jobs.get(user_id)
        if job is None or job.status != "running":
            raise SyncNotRunningError(support_details="student sync is not running")
        await self._control.request_student_stop(user_id)
