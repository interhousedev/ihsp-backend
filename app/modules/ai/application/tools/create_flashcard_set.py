"""Tool (write): create a flash card set."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.application.tools.card_args import (
    MAX_CARDS,
    CardArg,
    card_items,
)
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField
from app.shared.contracts.flashcards import FlashcardsApi

from pydantic import Field


class CreateFlashcardSetArgs(ToolArgs):
    """A new set with its cards."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    cards: list[CardArg] = Field(min_length=1, max_length=MAX_CARDS)


class CreateFlashcardSet(WriteTool[CreateFlashcardSetArgs]):
    """Creates a set after the student approves it."""

    name = "create_flashcard_set"
    description = (
        "Create a new flash card set for the student (needs their approval). "
        f"Give a short title and 1-{MAX_CARDS} cards with a front (question) and "
        "a back (answer)."
    )
    args_model = CreateFlashcardSetArgs

    def __init__(self, flashcards: FlashcardsApi) -> None:
        """Store the flash cards API."""
        self.flashcards = flashcards

    async def preview(
        self, args: CreateFlashcardSetArgs, ctx: ToolContext
    ) -> PreviewData:
        """Show the title and the cards that would be created."""
        return PreviewData(
            title_key="ai-preview-create-flashcard-set",
            title_params={"title": args.title, "count": len(args.cards)},
            fields=[PreviewField(label_key="ai-field-title", value=args.title)],
            items=card_items(args.cards),
        )

    async def run(
        self, args: CreateFlashcardSetArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Create the set and return its id and size."""
        created = await self.flashcards.create_set(
            ctx.actor.user_id,
            args.title,
            [(card.front, card.back) for card in args.cards],
            source="ai",
            source_chat_id=ctx.chat_id,
            description=args.description,
        )
        return {
            "set_id": str(created.get("id", "")),
            "title": created.get("title", args.title),
            "card_count": created.get("card_count", len(args.cards)),
        }
