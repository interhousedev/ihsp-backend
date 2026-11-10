"""LMS Course tool `update_block`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.block_args import block_dict
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import BlockInput
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `update_block`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("step_id",)))
    async def update_block(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block_id: Annotated[str, Field(description="Block id from get_step.")],
        block: Annotated[BlockInput, Field(description="The new block content.")],
    ) -> dict[str, Any]:
        """Replace a block of a step draft with new content (same position).

        The block type may change. Example: block={"type": "text",
        "markdown": "New text"}. Read block ids with get_step.
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        return await kit.deps.lms_ops.update_block(
            actor, step_id, block_id, block_dict(block)
        )
