"""Students tool `get_chat`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "chats:read"


def register(kit: ToolKit) -> None:
    """Register `get_chat`."""

    @kit.tool(SCOPE)
    async def get_chat(
        chat_id: Annotated[UUID, Field(description="Id from list_chats.")],
        after_seq: Annotated[
            int, Field(ge=0, description="Last message number already read.")
        ] = 0,
        limit: Annotated[
            int, Field(ge=1, le=100, description="Most messages, 1 to 100.")
        ] = 50,
    ) -> dict[str, Any]:
        """Read one of the student's AI chats, oldest message first, one page."""
        actor = current_actor()
        page = await kit.deps.history_tools.get_chat(
            actor.user_id, chat_id, after_seq=after_seq, limit=limit
        )
        return mark_untrusted(page, "title", "messages[].text")
