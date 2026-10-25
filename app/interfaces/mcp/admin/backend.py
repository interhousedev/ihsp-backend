"""The only way Administration tools reach the backend: read-only names."""

from typing import Any

from app.interfaces.mcp.constants import ADMIN_READ_TOOLS
from app.interfaces.mcp.errors import McpToolNotAllowedError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.jsonable import to_jsonable
from app.interfaces.mcp.toolkit import ToolKit


async def call_admin_tool(
    kit: ToolKit, tool: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Forward a read-only tool to AdminToolBackend as the calling actor.

    Arguments are sent as JSON values (ids and dates as strings), like the
    Administration assistant sends them; `None` arguments are dropped.
    """
    if tool not in ADMIN_READ_TOOLS:
        raise McpToolNotAllowedError(params={"tool": tool})
    sent = {
        key: to_jsonable(value) for key, value in arguments.items() if value is not None
    }
    return await kit.deps.admin_tools.call(tool, sent, current_actor())
