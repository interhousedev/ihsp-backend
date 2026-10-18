"""Task notebooks.reconcile_subject_materials: sync a subject's notebooks.

Started by POST .../reconcile, which answers 202 with the job id; the totals are read
from the job (GET .../reconcile/{job_id}).
"""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container
from app.modules.notebooks.application.reconcile_subject_materials import (
    RECONCILE_TASK,
)
from app.shared.jobs import RedisJobTracker, job_progress, run_job


@broker.task(task_name=RECONCILE_TASK)
async def reconcile_subject_materials(
    subject_id: str, owner_id: str | None = None, job_id: str | None = None
) -> int:
    """Run the check of a subject (one owner's notebooks when ``owner_id`` is set)."""
    container = get_container()
    async with run_job(
        RedisJobTracker(container.redis),
        RECONCILE_TASK,
        f"Subject materials {subject_id}",
        job_id=job_id,
    ) as job:
        if job is None:
            return 0  # an admin stopped it while it was queued
        result = await container.notebooks.reconcile_subject_materials.execute(
            UUID(subject_id), None if owner_id is None else UUID(owner_id)
        )
        await job_progress(
            done=result.notebooks,
            total=result.notebooks,
            add={
                "added": result.added,
                "already_present": result.already_present,
                "skipped": result.skipped,
            },
        )
        return result.notebooks
    return 0
