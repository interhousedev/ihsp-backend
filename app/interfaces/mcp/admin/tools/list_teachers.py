"""Administration tool `list_teachers`."""

from typing import Annotated, Any

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "people:read"


def register(kit: ToolKit) -> None:
    """Register `list_teachers`."""

    @kit.tool(SCOPE)
    async def list_teachers(
        query: Annotated[
            str | None, Field(max_length=100, description="Name or login filter.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Most results.")] = 50,
    ) -> dict[str, Any]:
        """List teacher accounts: id, name, login and status."""
        return await call_admin_tool(
            kit, "list_teachers", {"query": query, "limit": limit}
        )
