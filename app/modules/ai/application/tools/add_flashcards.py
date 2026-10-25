"""Tool (write): add cards to an existing flash card set."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.application.tools.card_args import (
    MAX_CARDS,
    CardArg,
    card_items,
)
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField
from app.shared.contracts.flashcards import FlashcardsApi

from pydantic import Field


class AddFlashcardsArgs(ToolArgs):
    """Cards to add to one of the student's sets."""

    set_id: UUID
    cards: list[CardArg] = Field(min_length=1, max_length=MAX_CARDS)


class AddFlashcards(WriteTool[AddFlashcardsArgs]):
    """Adds cards to a set after the student approves."""

    name = "add_flashcards"
    description = (
        "Add cards to one of the student's flash card sets (needs their approval)."
    )
    args_model = AddFlashcardsArgs

    def __init__(self, flashcards: FlashcardsApi) -> None:
        """Store the flash cards API."""
        self.flashcards = flashcards

    async def _set_title(self, args: AddFlashcardsArgs, ctx: ToolContext) -> str:
        found = await self.flashcards.get_set(args.set_id, ctx.actor.user_id)
        if found is None:
            raise ToolFailedError(support_details="flash card set not found")
        return str(found.get("title", ""))

    async def validate(self, args: AddFlashcardsArgs, ctx: ToolContext) -> None:
        """The set must still exist and belong to the student."""
        await self._set_title(args, ctx)

    async def preview(self, args: AddFlashcardsArgs, ctx: ToolContext) -> PreviewData:
        """Show the set and the cards that would be added."""
        title = await self._set_title(args, ctx)
        return PreviewData(
            title_key="ai-preview-add-flashcards",
            title_params={"title": title, "count": len(args.cards)},
            fields=[PreviewField(label_key="ai-field-set", value=title)],
            items=card_items(args.cards),
        )

    async def run(self, args: AddFlashcardsArgs, ctx: ToolContext) -> dict[str, Any]:
        """Add the cards and return the set's new size."""
        updated = await self.flashcards.add_cards(
            ctx.actor.user_id,
            args.set_id,
            [(card.front, card.back) for card in args.cards],
        )
        return {
            "set_id": str(args.set_id),
            "added": len(args.cards),
            "card_count": updated.get("card_count"),
        }
