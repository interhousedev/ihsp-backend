"""Students tool `create_flashcard_set`."""

from typing import Annotated, Any

from app.interfaces.mcp.cards import CardList, card_pairs
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "flashcards:write"


def register(kit: ToolKit) -> None:
    """Register `create_flashcard_set`."""

    @kit.tool(SCOPE, read_only=False)
    async def create_flashcard_set(
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="Name of the set.")
        ],
        cards: CardList,
        description: Annotated[
            str | None, Field(max_length=1000, description="Optional description.")
        ] = None,
    ) -> dict[str, Any]:
        """Create a new flash card set for the student; it is marked as made via MCP.

        Sets cannot be deleted through MCP.
        """
        actor = current_actor()
        return await kit.deps.flashcards.create_set(
            actor.user_id,
            title,
            card_pairs(cards),
            source="mcp",
            description=description,
        )
