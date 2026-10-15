"""Task academic.resync_materials: replace EMIS materials in some terms (admin)."""

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container
from app.shared.jobs import RedisJobTracker, run_job


@broker.task(task_name="academic.resync_materials")
async def resync_materials(
    terms: list[list[str | int]], job_id: str | None = None
) -> int:
    """Purge and download the materials; ``terms`` holds [academic year, half]."""
    container: Container = get_container()
    chosen = [(str(year), int(half)) for year, half in terms]
    label = "EMIS materials " + ", ".join(f"{year}/{half}" for year, half in chosen)
    async with run_job(
        RedisJobTracker(container.redis),
        "academic.resync_materials",
        label,
        job_id=job_id,
    ) as job:
        if job is None:
            return 0  # an admin stopped it while it was queued
        return await container.academic.marks.resync_materials.execute(chosen)
    return 0
