"""Author tool (write): append a Markdown text block to a step."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    course_step,
    first_lines,
    step_title,
)
from app.modules.ai.application.tools.lms_writes import append_block
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData
from app.shared.contracts.lms_blocks import build_text_block

from pydantic import Field


class AddTextBlockArgs(ToolArgs):
    """The step and the Markdown of the new block."""

    step_id: UUID = Field(description="Step id from the course outline.")
    markdown: str = Field(
        min_length=1,
        max_length=30_000,
        description="Markdown; headings from ###, LaTeX in $...$ or $$...$$.",
    )


class AddTextBlock(AuthorWriteTool[AddTextBlockArgs]):
    """Adds a text block after the step's last block."""

    name = "add_text_block"
    description = (
        "Append ONE Markdown text block to the end of a step's draft (needs "
        "approval); existing blocks stay as they are. Use it to add an explanation, "
        "a worked example or a summary. To restructure a step or write a whole "
        "lesson use replace_step_content (one call). Result: step_id, block (its "
        "number), blocks_total. Example: add_text_block "
        '{"step_id": "0192f0c4-...-7d1e", "markdown": "### Worked example\\n..."}'
    )
    args_model = AddTextBlockArgs

    async def validate(self, args: AddTextBlockArgs, ctx: ToolContext) -> None:
        """The step must belong to the chat's course."""
        await course_step(self.bindings, ctx, args.step_id)

    async def preview(self, args: AddTextBlockArgs, ctx: ToolContext) -> PreviewData:
        """Show the step and the first lines of the text."""
        draft = await course_step(self.bindings, ctx, args.step_id)
        return PreviewData(
            title_key="ai-preview-add-text-block",
            title_params={"step": step_title(draft)},
            items=first_lines(args.markdown),
        )

    async def run(self, args: AddTextBlockArgs, ctx: ToolContext) -> dict[str, Any]:
        """Append the block (marked as changed by AI)."""
        block = build_text_block(args.markdown)
        return await append_block(self.bindings, ctx, args.step_id, block)
