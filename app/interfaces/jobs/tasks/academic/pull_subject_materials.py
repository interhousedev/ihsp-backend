"""Task academic.pull_subject_materials: EMIS materials of one subject (admin)."""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container
from app.modules.academic.domain.schedule.material_scope import (
    MaterialScope,
    PullMode,
)
from app.shared.jobs import RedisJobTracker, run_job


@broker.task(task_name="academic.pull_subject_materials")
async def pull_subject_materials(
    subject_id: str,
    mode: PullMode = "full",
    teacher_id: str | None = None,
    group_id: str | None = None,
    terms: list[list[str | int]] | None = None,
    job_id: str | None = None,
) -> int:
    """Re-import (full) or fill (soft) the subject's lessons; terms None = current."""
    container: Container = get_container()
    scope = MaterialScope(
        subject_id=UUID(subject_id),
        teacher_id=UUID(teacher_id) if teacher_id else None,
        mode=mode,
    )
    chosen = None if terms is None else [(str(year), int(half)) for year, half in terms]
    async with run_job(
        RedisJobTracker(container.redis),
        "subject_materials_pull",
        f"EMIS {mode} pull: subject {subject_id}",
        job_id=job_id,
    ) as job:
        if job is None:
            return 0  # an admin stopped it while it was queued
        return await container.academic.marks.resync_materials.execute(
            chosen, scope=scope, group_id=UUID(group_id) if group_id else None
        )
    return 0
