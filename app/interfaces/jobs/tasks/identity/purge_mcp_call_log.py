"""Task ``identity.purge_mcp_call_log``: drop call traces past the retention period."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="identity.purge_mcp_call_log")
async def purge_mcp_call_log() -> int:
    """Run daily; returns how many traces were removed (B1)."""
    removed: int = await get_container().identity.auth.purge_mcp_call_log.execute()
    return removed
