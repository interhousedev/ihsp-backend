"""Students tool `list_flashcard_sets`."""

from typing import Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

SCOPE = "flashcards:read"


def register(kit: ToolKit) -> None:
    """Register `list_flashcard_sets`."""

    @kit.tool(SCOPE)
    async def list_flashcard_sets() -> dict[str, Any]:
        """List the student's flash card sets with card counts and today's due cards."""
        actor = current_actor()
        sets = await kit.deps.flashcards.list_sets(actor.user_id)
        return mark_untrusted(
            {
                "sets": [
                    {
                        **row,
                        "links": kit.deps.web_links.flashcard_set(UUID(str(row["id"]))),
                    }
                    for row in sets
                ]
            },
            "sets[].title",
            "sets[].description",
        )
