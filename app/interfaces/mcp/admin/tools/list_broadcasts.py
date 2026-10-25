"""Administration tool `list_broadcasts`."""

from typing import Annotated, Any, Literal

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "broadcasts:read"


def register(kit: ToolKit) -> None:
    """Register `list_broadcasts`."""

    @kit.tool(SCOPE)
    async def list_broadcasts(
        status: Annotated[
            Literal["draft", "scheduled", "sending", "sent", "cancelled"] | None,
            Field(description="Only broadcasts in this status."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Most results.")] = 20,
    ) -> dict[str, Any]:
        """List broadcasts with their audience, status and delivery statistics."""
        return await call_admin_tool(
            kit, "list_broadcasts", {"status": status, "limit": limit}
        )
