"""Students tool `get_flashcard_set`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.errors import McpNotFoundError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "flashcards:read"


def register(kit: ToolKit) -> None:
    """Register `get_flashcard_set`."""

    @kit.tool(SCOPE)
    async def get_flashcard_set(
        set_id: Annotated[UUID, Field(description="Set id from list_flashcard_sets.")],
    ) -> dict[str, Any]:
        """Show one of the student's flash card sets with all its cards."""
        actor = current_actor()
        found = await kit.deps.flashcards.get_set(set_id, actor.user_id)
        if found is None:
            raise McpNotFoundError()
        return found
