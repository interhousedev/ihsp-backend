"""Start and read the reconcile job: the subject-notebook check runs in the worker."""

import datetime as dt
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.v1.notebooks.schemas_admin_materials import (
    ReconcileJobAccepted,
    ReconcileJobStatus,
)
from app.modules.notebooks.application.reconcile_subject_materials import (
    RECONCILE_TASK,
)
from app.shared.jobs import JobNotFoundError, RedisJobTracker, enqueue
from app.shared.tasks import TaskKickFailedError


async def start_reconcile(
    container: Container, subject_id: UUID, owner_id: UUID | None, started_by: UUID
) -> ReconcileJobAccepted:
    """Queue the check of the subject's notebooks and return its job id (202)."""
    tracker = RedisJobTracker(container.redis)
    job_id = await enqueue(
        tracker,
        RECONCILE_TASK,
        f"Subject materials {subject_id}",
        started_by=str(started_by),
    )
    try:
        await container.kicker.kick(
            RECONCILE_TASK,
            subject_id=str(subject_id),
            owner_id=None if owner_id is None else str(owner_id),
            job_id=job_id,
        )
    except TaskKickFailedError:
        job = await tracker.get(job_id)
        if job is not None:
            job.status = "failed"
            job.note = "the task queue refused the job"
            job.finished_at = dt.datetime.now(dt.UTC).isoformat()
            await tracker.save(job)
        raise
    return ReconcileJobAccepted(job_id=job_id, status="queued")


async def reconcile_status(
    container: Container, job_id: str, *, started_by: UUID | None
) -> ReconcileJobStatus:
    """The totals of a reconcile job; `started_by` limits it to that user."""
    job = await RedisJobTracker(container.redis).get(job_id)
    if (
        job is None
        or job.kind != RECONCILE_TASK
        or (started_by is not None and job.started_by != str(started_by))
    ):
        raise JobNotFoundError(params={"job_id": job_id})
    return ReconcileJobStatus(
        job_id=job.id,
        status=job.status,
        done=job.status == "done",
        notebooks=job.total or 0,
        added=job.counters.get("added", 0),
        already_present=job.counters.get("already_present", 0),
        skipped=job.counters.get("skipped", 0),
    )
