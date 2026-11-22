"""Task admission.essay_keys_rotate: move every essay to a new per-student key."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admission.essay_keys_rotate")
async def essay_keys_rotate(run_id: str) -> None:
    """Run the rotation `run_id`; a no-op once another run holds the lease."""
    await get_container().admission.essay_keys.run_rotation(UUID(run_id))
