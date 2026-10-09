"""Task academic.bootstrap_group: import an unknown group's timetable from EMIS."""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.bootstrap_group")
async def bootstrap_group(user_id: UUID, group_id: UUID) -> str:
    """Create the group's entries, rooms, teachers and lessons; return the status."""
    container: Container = get_container()
    result = await container.academic.emis_import.bootstrap_group.execute(
        group_id=group_id, user_id=user_id
    )
    return result.status
