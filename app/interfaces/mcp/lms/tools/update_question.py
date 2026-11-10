"""LMS Course tool `update_question`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.block_args import question_dict
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import QuestionInput
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `update_question`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("step_id",)))
    async def update_question(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block_id: Annotated[str, Field(description="Test block id from get_step.")],
        question_id: Annotated[str, Field(description="Question id from get_step.")],
        question: Annotated[QuestionInput, Field(description="The new question.")],
    ) -> dict[str, Any]:
        """Replace one question of a test block with a new question.

        Give the whole question, as in add_question. Read ids with get_step.
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        return await kit.deps.lms_ops.update_question(
            actor, step_id, block_id, question_id, question_dict(question)
        )
