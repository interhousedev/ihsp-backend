"""Task notebooks.build_source_guide: summary, key topics and questions of a source."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(
    task_name="notebooks.build_source_guide", retry_on_error=True, max_retries=2
)
async def build_source_guide(source_id: UUID) -> None:
    """Build the guide (§ 3.2.5); provider failures only mark the guide failed."""
    await get_container().notebooks.build_source_guide.execute(source_id)
