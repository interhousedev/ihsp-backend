"""Task academic.sync_class_hours: store the EMIS bells in the current term (ACA-4).

Kicked after a registration; the 20:00 sync run also calls the use case once.
"""

from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.sync_class_hours")
async def sync_class_hours(user_id: UUID) -> str:
    """Read the bells through the student's EMIS link; return what happened."""
    container: Container = get_container()
    result = await container.academic.emis_import.sync_class_hours.execute(user_id)
    return result.status
