"""Tasks of the initial student sync with proof (see RunStudentSync).

`academic.run_student_sync` runs one attempt for one student; it is kicked after a
registration and by the settings page. `academic.retry_student_syncs` runs every few
minutes and kicks every student whose job is due (pending, failed with backoff, or a
run whose worker died), so a lost kick only delays the sync.
"""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.run_student_sync")
async def run_student_sync(user_id: UUID) -> None:
    """One attempt; the outcome is recorded on the job row, never re-raised."""
    container: Container = get_container()
    await container.academic.marks.run_student_sync.execute(user_id)


@broker.task(task_name="academic.retry_student_syncs")
async def retry_student_syncs() -> int:
    """Kick the due initial syncs; return how many were due."""
    container: Container = get_container()
    return await container.academic.marks.retry_student_syncs.execute()
