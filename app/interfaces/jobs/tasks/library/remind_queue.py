"""library.remind_queue: remind librarians of materials waiting too long (daily)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.remind_queue")
async def remind_queue() -> int:
    """Return how many reminders were queued."""
    return int(await get_container().library.materials.remind_queue.execute())
