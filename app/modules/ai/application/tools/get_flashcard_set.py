"""Tool: one flash card set with its cards."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.flashcards import FlashcardsApi


class GetFlashcardSetArgs(ToolArgs):
    """A set."""

    set_id: UUID


class GetFlashcardSet(ReadTool[GetFlashcardSetArgs]):
    """A set with its cards."""

    name = "get_flashcard_set"
    description = "A flash card set of the student with all its cards."
    args_model = GetFlashcardSetArgs

    def __init__(self, flashcards: FlashcardsApi) -> None:
        """Store the flash cards API."""
        self.flashcards = flashcards

    async def run(self, args: GetFlashcardSetArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the set, or fail if it is not the student's."""
        found = await self.flashcards.get_set(args.set_id, ctx.actor.user_id)
        if found is None:
            raise ToolFailedError(support_details="flash card set not found")
        return found
