"""Task files.process: extract text of an uploaded file and mark it ready."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="files.process", retry_on_error=True, max_retries=3)
async def process(file_id: UUID) -> None:
    """Run the processing step; repeated runs are harmless."""
    await get_container().files.process_file.execute(file_id)
