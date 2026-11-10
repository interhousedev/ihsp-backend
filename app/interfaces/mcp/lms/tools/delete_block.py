"""LMS Course tool `delete_block`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `delete_block`."""

    @kit.tool(SCOPE, read_only=False, destructive=True, log=LogSpec(keep=("step_id",)))
    async def delete_block(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block_id: Annotated[str, Field(description="Block id from get_step.")],
    ) -> dict[str, Any]:
        """Delete one block from a step draft.

        Questions in it are lost; cannot be undone except by restore_version.
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        result = await kit.deps.lms_ops.delete_block(actor, step_id, block_id)
        return result if isinstance(result, dict) else {"items": result}
