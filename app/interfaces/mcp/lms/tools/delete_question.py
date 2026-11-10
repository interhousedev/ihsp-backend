"""LMS Course tool `delete_question`."""

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
    """Register `delete_question`."""

    @kit.tool(SCOPE, read_only=False, destructive=True, log=LogSpec(keep=("step_id",)))
    async def delete_question(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block_id: Annotated[str, Field(description="Block id from get_step.")],
        question_id: Annotated[str, Field(description="Question id from get_step.")],
    ) -> dict[str, Any]:
        """Delete one question from a test block of a step draft."""
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        result = await kit.deps.lms_ops.delete_question(
            actor, step_id, block_id, question_id
        )
        return result if isinstance(result, dict) else {"items": result}
