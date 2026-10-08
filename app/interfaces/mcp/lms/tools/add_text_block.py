"""LMS Course tool `add_text_block`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.blocks import build_text_block
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:draft"


def register(kit: ToolKit) -> None:
    """Register `add_text_block`."""

    @kit.tool(SCOPE, read_only=False)
    async def add_text_block(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        markdown: Annotated[
            str,
            Field(min_length=1, max_length=50000, description="Markdown text."),
        ],
    ) -> dict[str, Any]:
        """Append a Markdown text block to the end of a step draft.

        Existing blocks are never changed. The change is a pending change marked
        "via MCP". If a person saved the step at the same moment, the call fails
        with a conflict: read the step again with get_step and retry.
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        return await kit.deps.lms_commands.add_block(
            actor, step_id, build_text_block(markdown), via_mcp=True
        )
