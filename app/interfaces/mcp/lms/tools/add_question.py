"""LMS Course tool `add_question`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.blocks import build_question
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.lms.inputs import QuestionInput
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:draft"


def register(kit: ToolKit) -> None:
    """Register `add_question`."""

    @kit.tool(SCOPE, read_only=False)
    async def add_question(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block_id: Annotated[
            str, Field(min_length=1, description="Id of a test block of the step.")
        ],
        question: QuestionInput,
    ) -> dict[str, Any]:
        """Append one question to an existing test block of a step draft.

        Existing questions are never changed. The change is a pending change marked
        "via MCP".
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        return await kit.deps.lms_commands.add_question(
            actor, step_id, block_id, build_question(question), via_mcp=True
        )
