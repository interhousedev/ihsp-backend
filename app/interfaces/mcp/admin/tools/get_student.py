"""Administration tool `get_student`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.admin.backend import call_admin_tool
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "people:read"


def register(kit: ToolKit) -> None:
    """Register `get_student`."""

    @kit.tool(SCOPE)
    async def get_student(
        user_id: Annotated[UUID, Field(description="Student id from search_users.")],
    ) -> dict[str, Any]:
        """Show a student's profile: group, subgroup, status and academic summary.

        The call is written to the audit log.
        """
        return await call_admin_tool(kit, "get_student", {"user_id": user_id})
