"""Task ``identity.offer_mcp_scopes``: offer new MCP scopes once per release."""

from app.interfaces.jobs.broker import broker
from app.interfaces.jobs.context import get_container


@broker.task(task_name="identity.offer_mcp_scopes")
async def offer_mcp_scopes() -> int:
    """Run daily; returns how many offers were made (A7)."""
    made: int = await get_container().identity.auth.offer_mcp_scopes.execute()
    return made
