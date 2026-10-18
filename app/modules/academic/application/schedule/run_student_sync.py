"""Run one attempt of a student's initial sync and record the proof; retry the due ones.

One attempt = timetable (subgroup) first, then marks. Any failure is recorded on the
job row (last_error, next attempt with backoff); after MAX_ATTEMPTS an audit event
"student_sync.gave_up" is written for administrators, and the job waits for a manual
request. Nothing here re-raises, so a failed attempt never looks like a crashed task.
"""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.marks.backfill_student import BackfillStudent
from app.modules.academic.application.schedule.common import UowFactory
from app.modules.academic.application.schedule.student_sync_jobs import (
    MAX_ATTEMPTS,
    JobStatus,
    StudentSyncJob,
    StudentSyncJobs,
    backoff_seconds,
)
from app.modules.academic.application.schedule.sync_student_all import SyncStudentAll
from app.modules.academic.domain.marks.sync import SyncCounters
from app.shared.actor import SYSTEM_USER_ID, Actor, Role
from app.shared.clock import Clock
from app.shared.contracts.identity import IdentityDirectory
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

TASK_NAME = "academic.run_student_sync"
RETRY_BATCH = 50


class StudentSyncIncompleteError(Exception):
    """An attempt ended without the subgroup or the marks (a reason, not a crash)."""


class RunStudentSync:
    """Claim the job, sync timetable then marks, store the outcome."""

    def __init__(
        self,
        *,
        jobs: StudentSyncJobs,
        sync_all: SyncStudentAll,
        backfill: BackfillStudent,
        uow_factory: UowFactory,
        clock: Clock,
        identity: IdentityDirectory,
    ) -> None:
        """Store the collaborators."""
        self._identity = identity
        self._jobs = jobs
        self._sync_all = sync_all
        self._backfill = backfill
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, user_id: UUID) -> StudentSyncJob | None:
        """One attempt if the job is due; return the job as it is afterwards."""
        claimed = await self._jobs.claim(user_id, self._clock.now())
        if claimed is None:
            return await self._jobs.get(user_id)
        try:
            subgroup, marks = await self._sync(user_id)
        except Exception as exc:  # recorded below; the retry job picks it up
            await self._record_failure(claimed, exc)
        else:
            await self._jobs.succeed(
                user_id, self._clock.now(), subgroup=subgroup, marks_count=marks
            )
            log.info(
                "student_sync_succeeded",
                user_id=str(user_id),
                attempt=claimed.attempts,
                subgroup=subgroup,
                marks=marks,
            )
        return await self._jobs.get(user_id)

    async def _sync(self, user_id: UUID) -> tuple[int | None, int]:
        timetable = await self._sync_all.execute(user_id, with_marks=False)
        if timetable != "synced":
            raise StudentSyncIncompleteError(f"timetable:{timetable}")
        counters = SyncCounters()
        outcome = await self._backfill.execute(user_id, counters=counters)
        if outcome.status != "ok":
            raise StudentSyncIncompleteError(f"marks:{outcome.status}")
        async with self._uow_factory() as uow:
            student = await uow.students.get(user_id)
        return (student.subgroup if student else None), counters.marks_new

    async def _record_failure(self, job: StudentSyncJob, exc: Exception) -> None:
        now = self._clock.now()
        error = f"{type(exc).__name__}: {exc}"
        code = getattr(exc, "code", None)
        if code:
            error = f"{code}: {exc}"
        await self._jobs.fail(
            job.user_id,
            now,
            error=error,
            next_attempt_at=now + dt.timedelta(seconds=backoff_seconds(job.attempts)),
        )
        log.warning(
            "student_sync_failed",
            user_id=str(job.user_id),
            attempt=job.attempts,
            error=error[:200],
        )
        if job.attempts >= MAX_ATTEMPTS:
            await self._alert_gave_up(job, error)

    async def _alert_gave_up(self, job: StudentSyncJob, error: str) -> None:
        """Tell every administrator, and leave an audit event."""
        log.error(
            "student_sync_gave_up", user_id=str(job.user_id), attempts=job.attempts
        )
        admins = await self._identity.user_ids_with_roles([Role.ADMIN])
        async with self._uow_factory() as uow:
            uow.notify(
                *(
                    NotificationDraft(
                        user_id=admin,
                        type=NotificationType.STUDENT_SYNC_FAILED,
                        payload={
                            "attempts": job.attempts,
                            "student_id": str(job.user_id),
                        },
                        dedupe_key=f"student-sync-failed:{job.user_id}:{admin}",
                    )
                    for admin in admins
                )
            )
            uow.audit(
                AuditDraft(
                    type="student_sync.gave_up",
                    user_id=job.user_id,
                    actor_id=SYSTEM_USER_ID,
                    metadata={"attempts": job.attempts, "last_error": error[:500]},
                )
            )
            await uow.commit()


class RetryStudentSyncs:
    """Periodic: queue one run for every student whose job is due."""

    def __init__(
        self, *, jobs: StudentSyncJobs, kicker: TaskKicker, clock: Clock
    ) -> None:
        """Store the collaborators."""
        self._jobs = jobs
        self._kicker = kicker
        self._clock = clock

    async def execute(self) -> int:
        """Kick the due students; a refused kick leaves the job due for the next run."""
        due = await self._jobs.due(self._clock.now(), RETRY_BATCH)
        for user_id in due:
            try:
                await self._kicker.kick(TASK_NAME, user_id=str(user_id))
            except Exception:
                log.warning("student_sync_retry_kick_failed", user_id=str(user_id))
        return len(due)


class ListStudentSyncJobs:
    """Administration's view: initial syncs in one status, newest first."""

    def __init__(self, *, jobs: StudentSyncJobs) -> None:
        """Store the job port."""
        self._jobs = jobs

    async def execute(
        self, actor: Actor, status: JobStatus, limit: int
    ) -> list[StudentSyncJob]:
        """Admins only."""
        actor.require(Role.ADMIN)
        return await self._jobs.list_by_status(status, limit)
