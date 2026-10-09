"""library.rights_review: warn librarians about book permissions ending soon (daily)."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="library.rights_review")
async def rights_review() -> int:
    """Return how many messages were queued."""
    return int(await get_container().library.materials.review_rights.execute())
