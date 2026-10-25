"""Students tool `update_flashcard`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.cards import CardText
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "flashcards:write"


def register(kit: ToolKit) -> None:
    """Register `update_flashcard`."""

    @kit.tool(SCOPE, read_only=False)
    async def update_flashcard(
        card_id: Annotated[UUID, Field(description="Card id from get_flashcard_set.")],
        front: Annotated[
            CardText | None, Field(description="New question side.")
        ] = None,
        back: Annotated[CardText | None, Field(description="New answer side.")] = None,
    ) -> dict[str, Any]:
        """Change the text of one card in the student's own sets.

        Give front, back or both. Cards in sets owned by someone else are refused.
        """
        actor = current_actor()
        if front is None and back is None:
            raise McpInvalidInputError(params={"reason": "give front, back or both"})
        return await kit.deps.flashcards.update_card(
            actor.user_id, card_id, front, back
        )
