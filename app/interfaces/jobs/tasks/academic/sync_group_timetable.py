"""Task academic.sync_group_timetable: import a group's timetable from EMIS (ACA-1).

Kicked after a registration and when a student moves to another group, so the
materials of the whole term come too; the 20:00 sync run calls the use case itself for
every group with students.
"""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.sync_group_timetable")
async def sync_group_timetable(user_id: UUID, group_id: UUID) -> str:
    """Update the group's entries, lessons and lesson details; return the status."""
    container: Container = get_container()
    result = await container.academic.emis_import.sync_group_timetable.execute(
        group_id=group_id, user_id=user_id, full_term=True
    )
    return result.status
