"""Task academic.sync_group_curriculum: store a group's EMIS curriculum once.

Kicked when a student's profile refresh finds a group without a stored curriculum (a
registration, a group seen for the first time, a later sync of a group still without
one). A group that has one is left alone; Administration refreshes it by hand.
"""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container

ALREADY_STORED = "exists"


@broker.task(task_name="academic.sync_group_curriculum")
async def sync_group_curriculum(group_id: UUID) -> str:
    """Read the curriculum through a student of the group; return what happened."""
    container: Container = get_container()
    result = await container.academic.emis_import.sync_group_curriculum.ensure(group_id)
    return result.status if result else ALREADY_STORED
