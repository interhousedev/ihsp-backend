"""Students tool `add_flashcards`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.cards import CardList, card_pairs
from app.interfaces.mcp.errors import McpNotFoundError, McpNotOwnerError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "flashcards:write"


def register(kit: ToolKit) -> None:
    """Register `add_flashcards`."""

    @kit.tool(SCOPE, read_only=False)
    async def add_flashcards(
        set_id: Annotated[UUID, Field(description="Set id from list_flashcard_sets.")],
        cards: CardList,
    ) -> dict[str, Any]:
        """Add cards to one of the student's own flash card sets."""
        actor = current_actor()
        owner = await kit.deps.flashcards.set_owner(set_id)
        if owner is None:
            raise McpNotFoundError()
        if owner != actor.user_id:
            raise McpNotOwnerError()
        return await kit.deps.flashcards.add_cards(
            actor.user_id, set_id, card_pairs(cards)
        )
