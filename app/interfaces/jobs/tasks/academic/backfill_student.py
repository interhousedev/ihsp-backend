"""Task academic.backfill_student: silent import of semesters 1-4 (SYNC-4)."""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.backfill_student")
async def backfill_student(user_id: UUID) -> None:
    """Refresh the profile and import every semester without notifications."""
    container: Container = get_container()
    await container.academic.marks.backfill_student.execute(user_id)
