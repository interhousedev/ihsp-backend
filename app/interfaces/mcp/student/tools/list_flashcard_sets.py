"""Students tool `list_flashcard_sets`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "flashcards:read"


def register(kit: ToolKit) -> None:
    """Register `list_flashcard_sets`."""

    @kit.tool(SCOPE)
    async def list_flashcard_sets() -> dict[str, Any]:
        """List the student's flash card sets with card counts and today's due cards."""
        actor = current_actor()
        sets = await kit.deps.flashcards.list_sets(actor.user_id)
        return {"sets": sets}
