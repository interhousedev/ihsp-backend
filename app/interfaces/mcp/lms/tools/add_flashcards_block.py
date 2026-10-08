"""LMS Course tool `add_flashcards_block`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.cards import CardList
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.blocks import build_flashcards_block
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:draft"


def register(kit: ToolKit) -> None:
    """Register `add_flashcards_block`."""

    @kit.tool(SCOPE, read_only=False)
    async def add_flashcards_block(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        cards: CardList,
    ) -> dict[str, Any]:
        """Append a flash cards block to the end of a step draft.

        The cards belong to the course, not to a student's own sets. The change is
        a pending change marked "via MCP".
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        return await kit.deps.lms_commands.add_block(
            actor, step_id, build_flashcards_block(cards), via_mcp=True
        )
