"""Task admission.app_review: run the agents of one full application review."""

from uuid import UUID

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="admission.app_review")
async def app_review(review_id: str) -> None:
    """Run the review; only a queued version is taken."""
    await get_container().admission.app_review.run(UUID(review_id))
