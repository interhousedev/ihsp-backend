"""Administration tool `list_groups`."""

from typing import Annotated, Any

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.params import SemesterParam
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "groups:read"


def register(kit: ToolKit) -> None:
    """Register `list_groups`."""

    @kit.tool(SCOPE)
    async def list_groups(
        semester: SemesterParam = None,
        query: Annotated[
            str | None, Field(max_length=50, description="Part of the group name.")
        ] = None,
    ) -> dict[str, Any]:
        """List groups with their curator, head student and student count."""
        return await call_admin_tool(
            kit, "list_groups", {"semester": semester, "query": query}
        )
