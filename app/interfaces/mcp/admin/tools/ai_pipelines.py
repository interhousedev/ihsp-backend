"""Administration tool `ai_pipelines`."""

from typing import Any

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "audit:read"


def register(kit: ToolKit) -> None:
    """Register `ai_pipelines`."""

    @kit.tool(SCOPE)
    async def ai_pipelines() -> dict[str, Any]:
        """List AI pipelines with their tasks and the connector and model they use."""
        return await call_admin_tool(kit, "ai_pipelines", {})
