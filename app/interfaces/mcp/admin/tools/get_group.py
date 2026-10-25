"""Administration tool `get_group`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "groups:read"


def register(kit: ToolKit) -> None:
    """Register `get_group`."""

    @kit.tool(SCOPE)
    async def get_group(
        group_id: Annotated[UUID, Field(description="Group id from list_groups.")],
    ) -> dict[str, Any]:
        """Show a group: curator, head student, subgroups and its students."""
        return await call_admin_tool(kit, "get_group", {"group_id": group_id})
