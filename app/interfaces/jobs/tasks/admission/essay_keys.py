"""Task admission.essay_keys_rotate: move every essay to a new per-student key."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admission.essay_keys_rotate")
async def essay_keys_rotate() -> None:
    """Run (or resume) the rotation the admin started; a no-op when none runs."""
    await get_container().admission.essay_keys.run_rotation()
