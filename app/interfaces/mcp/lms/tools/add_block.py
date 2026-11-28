"""LMS Course tool `add_block`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.block_args import parse_block
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `add_block`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("step_id", "position")))
    async def add_block(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "The block: an object with `type` and that type's fields, "
                    "exactly as list_block_types describes them."
                )
            ),
        ],
        position: Annotated[
            int | None,
            Field(
                ge=0,
                description="Index to insert at; omit to append to the end.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Add a block of any type to a step draft.

        Call list_block_types first: it lists every block type with its fields and
        an example. Existing blocks are never changed. A wrong field is refused with
        its path; fix it and call again. The change is a pending change marked
        "via MCP". If a person saved the step at the same moment, the call fails
        with a conflict: read the step again with get_step and retry.
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        built = parse_block(block)
        return await kit.deps.lms_commands.add_block(
            actor, step_id, built, via_mcp=True, position=position
        )
