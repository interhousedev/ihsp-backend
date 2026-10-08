"""Task ``academic.teacher_deactivated``: clear a deactivated teacher.

Kicked by the identity module after a teacher account is deactivated.
"""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.teacher_deactivated")
async def teacher_deactivated(teacher_id: str) -> tuple[int, int]:
    """Leave the teacher's entries and future lessons as "teacher needed"."""
    container = get_container()
    cleared: tuple[int, int] = (
        await container.academic.schedule.teacher_deactivated.execute(UUID(teacher_id))
    )
    return cleared
