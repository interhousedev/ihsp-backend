"""Task academic.fetch_lesson_materials: EMIS materials of one lesson (MCP fallback)."""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container
from app.shared.jobs import RedisJobTracker, run_job


@broker.task(task_name="academic.fetch_lesson_materials")
async def fetch_lesson_materials(lesson_id: str, user_id: str, job_id: str) -> None:
    """Fetch through the student's EMIS link; job labels hold ids only."""
    container: Container = get_container()
    use_case = container.academic.emis_import.fetch_lesson_materials
    if use_case is None:
        raise RuntimeError("fetch_lesson_materials is not wired")
    async with run_job(
        RedisJobTracker(container.redis),
        "lesson_materials_fetch",
        f"EMIS materials: lesson {lesson_id}",
        job_id=job_id,
    ) as job:
        if job is None:  # an admin stopped it while it was queued
            await use_case.record(UUID(lesson_id), UUID(user_id), job_id, "emis_busy")
            return
        await use_case.execute(UUID(lesson_id), UUID(user_id), job_id)
