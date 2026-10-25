"""Task notebooks.generate_artifact: create a Studio output (§ 3.4.0)."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="notebooks.generate_artifact")
async def generate_artifact(artifact_id: UUID) -> None:
    """Run the generation state machine; it only takes outputs that are queued."""
    await get_container().notebooks.generate_artifact.execute(artifact_id)
