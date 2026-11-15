"""Students tool `list_chats`."""

from typing import Annotated, Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "chats:read"


def register(kit: ToolKit) -> None:
    """Register `list_chats`."""

    @kit.tool(SCOPE)
    async def list_chats(
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page.")
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most chats to return, 1 to 50.")
        ] = 20,
    ) -> dict[str, Any]:
        """List the student's AI chats, newest first, with titles and dates."""
        actor = current_actor()
        page = await kit.deps.history_tools.list_chats(
            actor, cursor=cursor, limit=limit
        )
        return mark_untrusted(page, "chats[].title")
