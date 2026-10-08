"""Task ``academic.recompute_due_dates``: refresh automatic homework due dates.

Kicked by the schedule module with ``lesson_ids`` (strings) of changed lessons.
"""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="academic.recompute_due_dates")
async def recompute_due_dates(lesson_ids: list[str]) -> int:
    """Recompute due dates around the changed lessons; return how many changed."""
    container = get_container()
    changed: int = await container.academic.classwork.recompute_due_dates.execute(
        [UUID(value) for value in lesson_ids]
    )
    return changed
