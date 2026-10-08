"""Administration tool `sync_status`."""

from typing import Any

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "audit:read"


def register(kit: ToolKit) -> None:
    """Register `sync_status`."""

    @kit.tool(SCOPE)
    async def sync_status() -> dict[str, Any]:
        """Show the last EMIS sync runs: time, result and how many students failed."""
        return await call_admin_tool(kit, "sync_status", {})
