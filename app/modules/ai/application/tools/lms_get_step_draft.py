"""Author tool: the draft content of one step of the chat's course."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorReadTool
from app.modules.ai.application.tools.lms_common import course_step
from app.modules.ai.application.tools.lms_shapes import step_for_model
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field


class GetStepDraftArgs(ToolArgs):
    """A step of the course and, optionally, one of its blocks."""

    step_id: UUID = Field(description="Step id from the course outline.")
    block: int | None = Field(
        default=None,
        ge=1,
        le=40,
        description="Read only this block (1-based) in full; omit for all blocks.",
    )


class GetStepDraft(AuthorReadTool[GetStepDraftArgs]):
    """Title, numbered blocks and lock_version of a step draft."""

    name = "get_step_draft"
    description = (
        "Read the DRAFT of one step of this course: title, lock_version and its "
        "blocks numbered from 1 (text: markdown; test: settings and questions with "
        "options, correct flags and answers; flashcards: cards). Call it before you "
        "change or extend an existing step, and again after a draft-conflict. "
        "Long steps come back shortened (see `note`); pass `block` to read one "
        "block in full. Pass lock_version unchanged to replace_step_content. "
        'Example: get_step_draft {"step_id": "0192f0c4-...-7d1e"}'
    )
    args_model = GetStepDraftArgs

    async def run(self, args: GetStepDraftArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the step if it belongs to the chat's course."""
        draft = await course_step(self.bindings, ctx, args.step_id)
        return step_for_model(draft, args.block)
