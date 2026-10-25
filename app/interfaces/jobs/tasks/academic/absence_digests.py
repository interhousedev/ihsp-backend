"""Task ``academic.absence_digests``: curators' absence digests (WO-4).

Desired schedule: every 15 minutes from 12:00 to 20:45, Monday to Friday.
"""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.absence_digests")
async def absence_digests() -> dict[str, int]:
    """Queue the day's absence digest per curator and group, once lessons end."""
    container = get_container()
    result: dict[str, int] = (
        await container.academic.classwork.send_absence_digests.execute()
    )
    return result
