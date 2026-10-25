"""Task ai.purge_admin_chats (daily): delete Administration chats older than 90 days."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="ai.purge_admin_chats")
async def purge_admin_chats() -> int:
    """AI-12: Administration chats are kept 90 days; returns how many were removed."""
    return int(await get_container().ai.purge_admin_chats.execute())
