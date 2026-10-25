"""LMS Course tool `add_test_block`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.blocks import build_test_block
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.lms.inputs import QuestionList, QuizSettingsInput
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `add_test_block`."""

    @kit.tool(SCOPE, read_only=False)
    async def add_test_block(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        questions: QuestionList | None = None,
        settings: Annotated[
            QuizSettingsInput | None,
            Field(description="Test settings; defaults apply if omitted."),
        ] = None,
    ) -> dict[str, Any]:
        """Append a test block to the end of a step draft.

        Questions may be given now or added later with add_question (use the block
        id from the result). The change is a pending change marked "via MCP".
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        block = build_test_block(settings, questions or [])
        return await kit.deps.lms_commands.add_block(
            actor, step_id, block, via_mcp=True
        )
