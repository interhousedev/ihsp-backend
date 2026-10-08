"""Tool: the student's flash card sets."""

from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.flashcards import FlashcardsApi


class ListFlashcardSetsArgs(ToolArgs):
    """No arguments."""


class ListFlashcardSets(ReadTool[ListFlashcardSetsArgs]):
    """The student's sets."""

    name = "list_flashcard_sets"
    description = "List the student's flash card sets with card counts."
    args_model = ListFlashcardSetsArgs

    def __init__(self, flashcards: FlashcardsApi) -> None:
        """Store the flash cards API."""
        self.flashcards = flashcards

    async def run(
        self, args: ListFlashcardSetsArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the sets."""
        rows = await self.flashcards.list_sets(ctx.actor.user_id)
        return capped(rows)
