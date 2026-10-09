"""Administration tool `search_users`."""

from typing import Annotated, Any, Literal

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "people:read"


def register(kit: ToolKit) -> None:
    """Register `search_users`."""

    @kit.tool(SCOPE)
    async def search_users(
        query: Annotated[
            str,
            Field(
                min_length=1, max_length=100, description="Name or login to look for."
            ),
        ],
        roles: Annotated[
            list[Literal["student", "teacher", "admin", "lms_admin", "librarian"]] | None,
            Field(description="Only users with one of these roles."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50, description="Most results.")] = 20,
    ) -> dict[str, Any]:
        """Find users by name or login: id, name, login, roles and status."""
        arguments = {"query": query, "roles": roles, "limit": limit}
        return await call_admin_tool(kit, "search_users", arguments)
