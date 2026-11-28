"""Task `activities.mark_draft_no_shows`: mark picked volunteers who did not show up."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="activities.mark_draft_no_shows")
async def mark_draft_no_shows() -> int:
    """Return the number of items handled."""
    return int(await get_container().activities.drafts.mark_no_show_due())
