"""Task files.sweep_processing: restart stuck processing (every 10 minutes)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="files.sweep_processing")
async def sweep_processing() -> int:
    """Return how many files were sent to files.process again."""
    return int(await get_container().files.sweep_processing.execute())
