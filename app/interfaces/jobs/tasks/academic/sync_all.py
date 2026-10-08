"""Task academic.sync_all: one EMIS sync run for every student (SYNC-1).

Schedule for I1 (``cron_offset="Asia/Tashkent"``): ``SYNC_SLOTS`` below, one
entry per slot with ``kwargs={"slot": <slot>}``.
"""

from app.bootstrap.container import Container
from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container

SYNC_SLOTS: tuple[tuple[str, str], ...] = (
    ("11:30", "30 11 * * *"),
    ("15:00", "0 15 * * *"),
    ("20:00", "0 20 * * *"),
)


@broker.task(task_name="academic.sync_all")
async def sync_all(slot: str = "manual") -> None:
    """Run the sync for a slot: 11:30, 15:00, 20:00 (adds profile) or manual."""
    container: Container = get_container()
    await container.academic.marks.sync_all.execute(slot)
