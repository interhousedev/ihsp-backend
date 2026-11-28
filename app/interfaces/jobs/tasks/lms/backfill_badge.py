"""Task `lms.backfill_badge`: award a badge to those who already meet it."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="lms.backfill_badge")
async def backfill_badge(badge_id: str, cursor: int | None = None) -> dict[str, int]:
    """Run one batch; the batch queues the next one itself."""
    container = get_container()
    result = await container.lms.learning.badge_authoring.backfill.execute(
        UUID(badge_id), cursor
    )
    return {"awarded": result.awarded}
