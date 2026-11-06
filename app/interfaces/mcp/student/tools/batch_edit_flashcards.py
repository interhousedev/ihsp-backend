"""Students tool `batch_edit_flashcards`."""

from typing import Annotated, Any, Final
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.cards import CardText, FlashcardInput
from app.interfaces.mcp.errors import McpInvalidInputError, McpScopeError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.content_results import flashcard_set_result
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import BaseModel, Field

SCOPE = "flashcards:write"
DELETE_SCOPE = "flashcards:delete"
MAX_OPERATIONS: Final = 100


class CardEdit(BaseModel):
    """New text of one card; a side left out stays."""

    id: UUID = Field(description="Card id from get_flashcard_set.")
    front: CardText | None = None
    back: CardText | None = None


def register(kit: ToolKit) -> None:
    """Register `batch_edit_flashcards`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("set_id",)))
    async def batch_edit_flashcards(
        set_id: Annotated[UUID, Field(description="Set id from list_flashcard_sets.")],
        add: list[FlashcardInput] | None = None,
        update: list[CardEdit] | None = None,
        delete_ids: Annotated[
            list[UUID] | None, Field(description="Needs flashcards:delete as well.")
        ] = None,
    ) -> dict[str, Any]:
        """Add, edit and delete cards of one set at once: all of it, or nothing.

        At most 100 operations, and a set holds at most 500 cards. Edited cards keep
        their study progress. An id outside this set fails the whole batch.
        """
        actor = current_actor()
        new, edits, gone = add or [], update or [], delete_ids or []
        total = len(new) + len(edits) + len(gone)
        if not 1 <= total <= MAX_OPERATIONS:
            raise McpInvalidInputError(
                params={"reason": f"give 1 to {MAX_OPERATIONS} operations"}
            )
        if gone and not await kit.guard.has_scope(actor, DELETE_SCOPE):
            raise McpScopeError(params={"scope": DELETE_SCOPE})
        found = await kit.deps.content_tools.batch_edit_cards(
            actor.user_id,
            set_id,
            add=[card.model_dump() for card in new],
            update=[edit.model_dump() for edit in edits],
            delete_ids=gone,
        )
        return flashcard_set_result(kit.deps, found)
