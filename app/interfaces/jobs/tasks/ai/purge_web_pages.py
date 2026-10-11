"""Task ai.purge_web_pages (daily): delete the web pages past their retention."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="ai.purge_web_pages")
async def purge_web_pages() -> int:
    """Delete expired stored pages (with their vectors) and cached answers.

    Pages not returned for `EXA__PAGE_RETENTION_DAYS` days go, and answers older than
    `EXA__QUERY_CACHE_DAYS` days; returns the number of pages removed.
    """
    return int(await get_container().ai.purge_web_pages.execute())
