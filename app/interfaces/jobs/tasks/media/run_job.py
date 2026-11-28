"""Tasks ``media.run_job`` and ``media.deliver_pending``."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="media.run_job")
async def run_job(job_id: str) -> None:
    """Voice, render and deliver one job."""
    await get_container().media.run.execute(UUID(job_id))


@broker.task(task_name="media.deliver_pending")
async def deliver_pending() -> int:
    """Redeliver finished jobs the notebook has not accepted yet."""
    media = get_container().media
    ids = await media.store.list_undelivered()
    for job_id in ids:
        await media.run.execute(job_id)
    return len(ids)
