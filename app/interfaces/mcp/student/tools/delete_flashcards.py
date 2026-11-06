"""Students tool `delete_flashcards`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.content_results import flashcard_set_result
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "flashcards:delete"


def register(kit: ToolKit) -> None:
    """Register `delete_flashcards`."""

    @kit.tool(SCOPE, read_only=False, destructive=True, log=LogSpec(keep=("set_id",)))
    async def delete_flashcards(
        set_id: Annotated[UUID, Field(description="Set id from list_flashcard_sets.")],
        card_ids: Annotated[
            list[UUID],
            Field(min_length=1, max_length=100, description="Cards to delete."),
        ],
    ) -> dict[str, Any]:
        """Delete cards of one of the student's sets, and their study progress.

        An id outside this set deletes nothing. The set itself stays.
        """
        actor = current_actor()
        found = await kit.deps.content_tools.batch_edit_cards(
            actor.user_id, set_id, add=[], update=[], delete_ids=card_ids
        )
        return flashcard_set_result(kit.deps, found)
