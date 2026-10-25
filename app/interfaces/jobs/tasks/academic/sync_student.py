"""Task academic.sync_student: sync one student's marks (SYNC-8, UF-ID-12)."""

from typing import Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.sync_student")
async def sync_student(
    user_id: UUID,
    run_id: UUID | None = None,
    mode: Literal["regular", "backfill", "profile"] = "regular",
) -> None:
    """Sync one student; EMIS outages are raised so the broker may retry."""
    container: Container = get_container()
    await container.academic.marks.sync_student.execute(user_id, run_id, mode=mode)
