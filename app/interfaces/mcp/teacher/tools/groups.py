"""Teacher tools `list_my_groups` and `get_group_roster`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "groups:read"


def register(kit: ToolKit) -> None:
    """Register the group tools."""

    @kit.tool(SCOPE)
    async def list_my_groups() -> dict[str, Any]:
        """List the groups the teacher curates and the journals they teach."""
        return await kit.deps.teacher_tools.my_groups(current_actor())

    @kit.tool(SCOPE)
    async def get_group_roster(
        group_id: Annotated[UUID, Field(description="A group the teacher curates.")],
    ) -> dict[str, Any]:
        """A curated group with its students; other groups are refused."""
        return await kit.deps.teacher_tools.group_roster(current_actor(), group_id)
