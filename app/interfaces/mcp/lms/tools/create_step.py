"""LMS Course tool `create_step`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `create_step`."""

    @kit.tool(SCOPE, read_only=False)
    async def create_step(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        section_id: Annotated[
            str, Field(min_length=1, description="Section id from get_course.")
        ],
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="Step title.")
        ],
    ) -> dict[str, Any]:
        """Add a new empty step at the end of a section of a course draft.

        Add content with add_text_block, add_test_block and add_flashcards_block.
        The change is a pending change marked "via MCP".
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_commands.create_step(
            actor, course_id, section_id, title, via_mcp=True
        )
