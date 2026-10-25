"""LMS Course tool `update_step`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_step
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import BlockInput, BlockInputError, build_block
from app.shared.lms_scopes import MODULES_WRITE

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

SCOPE = MODULES_WRITE

COURSE_ID = Annotated[UUID, Field(description="Course id from list_courses.")]


def register(kit: ToolKit) -> None:
    """Register `update_step`."""

    @kit.tool(SCOPE, read_only=False)
    async def update_step(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        title: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=200, description="New title."),
        ] = None,
        blocks: Annotated[
            list[BlockInput] | None,
            Field(
                default=None,
                max_length=40,
                description="ALL blocks of the step: they REPLACE the current ones. "
                "Omit to keep them.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Rename a step and/or replace its blocks in the draft.

        Use add_text_block, add_test_block and add_flashcards_block to append instead.
        """
        actor = current_actor()
        await ensure_step(kit, actor, step_id)
        try:
            built = None if blocks is None else [build_block(b) for b in blocks]
        except BlockInputError as error:
            raise ToolError(str(error)) from error
        return await kit.deps.lms_commands.update_step(
            actor, step_id, title=title, blocks=built
        )
