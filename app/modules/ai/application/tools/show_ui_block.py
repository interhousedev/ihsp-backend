"""Tool: show one OpenUI block at the end of the answer message (Telegram only)."""

from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.openui.blocks import split_blocks
from app.shared.openui.validate import validate_block

from pydantic import Field

SHOW_UI_BLOCK = "show_ui_block"


class ShowUiBlockArgs(ToolArgs):
    """The block in OpenUI Lang, without a code fence."""

    block: str = Field(min_length=1, max_length=6000)


def block_source(raw: str) -> str:
    """The block code; a fence the model wrote around it is removed."""
    parts = split_blocks(raw)
    for part in parts:
        if part.kind == "block":
            return part.text
    return raw.strip("\n")


class ShowUiBlock(ReadTool[ShowUiBlockArgs]):
    """Checks a block; the bot appends it to the end of the answer message."""

    name = SHOW_UI_BLOCK
    description = (
        "Show a table, chart, diagram, timetable or link list as a visual block at "
        "the end of the answer. `block` is OpenUI Lang (root = ...), no code fence. "
        "Fetch the data first; fix the block if the result lists errors."
    )
    args_model = ShowUiBlockArgs

    async def run(self, args: ShowUiBlockArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the checked block, or fail with the problems for the model."""
        source = block_source(args.block)
        problems = validate_block(source)
        if problems:
            raise ToolFailedError(support_details="; ".join(problems[:5]))
        return {"shown": True, "block": source}
