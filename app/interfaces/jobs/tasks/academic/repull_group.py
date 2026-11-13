"""Task academic.repull_group: re-read a group's EMIS data after its first link.

Kicked after the commit of a registration (or a profile refresh) that gave the group
its EMIS id for the first time: forces the curriculum and the timetable (earlier weeks
too) and queues a student sync for the other members with a working EMIS link.
"""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.repull_group")
async def repull_group(group_id: UUID, user_id: UUID) -> str:
    """Re-pull the group through the student ``user_id``; return the status."""
    container: Container = get_container()
    return await container.academic.emis_import.repull_group.execute(
        group_id=group_id, user_id=user_id
    )
