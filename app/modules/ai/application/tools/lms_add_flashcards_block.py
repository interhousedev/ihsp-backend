"""Author tool (write): append a flash cards block to a step."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import course_step, step_title
from app.modules.ai.application.tools.lms_shapes import card_lines
from app.modules.ai.application.tools.lms_writes import append_block
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData
from app.shared.contracts.lms_blocks import FlashcardInput, build_flashcards_block

from pydantic import Field


class AddFlashcardsBlockArgs(ToolArgs):
    """The step and its cards."""

    step_id: UUID = Field(description="Step id from the course outline.")
    cards: list[FlashcardInput] = Field(
        min_length=1, max_length=200, description="Cards: one fact per card."
    )


class AddFlashcardsBlock(AuthorWriteTool[AddFlashcardsBlockArgs]):
    """Adds one flash cards block after the step's last block."""

    name = "add_flashcards_block"
    description = (
        "Append ONE flash cards block to the end of a step's draft (needs "
        "approval). One fact per card: a short question or term on the front, a "
        "short exact answer on the back; use the step's key terms and formulas. "
        "Students review these cards with spaced repetition. Result: step_id, "
        "block, blocks_total. Example: add_flashcards_block "
        '{"step_id": "0192f0c4-...-7d1e", "cards": [{"front": "Derivative of '
        'x^2", "back": "2x"}]}'
    )
    args_model = AddFlashcardsBlockArgs

    async def validate(self, args: AddFlashcardsBlockArgs, ctx: ToolContext) -> None:
        """The step must belong to the chat's course."""
        await course_step(self.bindings, ctx, args.step_id)

    async def preview(
        self, args: AddFlashcardsBlockArgs, ctx: ToolContext
    ) -> PreviewData:
        """Show the cards as ``front → back`` lines."""
        draft = await course_step(self.bindings, ctx, args.step_id)
        block = build_flashcards_block(args.cards)
        return PreviewData(
            title_key="ai-preview-add-flashcards-block",
            title_params={"step": step_title(draft), "count": len(args.cards)},
            items=card_lines(block),
        )

    async def run(
        self, args: AddFlashcardsBlockArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Append the cards (marked as changed by AI)."""
        block = build_flashcards_block(args.cards)
        return await append_block(self.bindings, ctx, args.step_id, block)
