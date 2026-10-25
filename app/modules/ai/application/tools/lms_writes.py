"""Draft writes shared by the author tools: append a block, find a section.

Appending goes through `LmsWorkspaceCommands.replace_step` with the step's current
blocks plus the new one, so the change carries the "via AI" mark and a concurrent
edit is caught by the lock version.
"""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_common import (
    course_step,
    draft_blocks,
    lms_call,
    scope_of,
    step_title,
    workspace_commands_of,
    workspace_of,
)
from app.modules.ai.domain.errors import ToolFailedError
from app.shared.contracts.lms import CourseBrief, CourseSectionBrief


def same_title(left: str, right: str) -> bool:
    """Compare titles like the LMS does: without case and extra spaces."""
    return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()


async def course_brief(bindings: LateBindings, ctx: ToolContext) -> CourseBrief:
    """Return the outline of the chat's course or fail."""
    scope = scope_of(ctx)
    brief = await lms_call(workspace_of(bindings).course_brief(scope.course_id))
    if brief is None:
        raise ToolFailedError(support_details="the course no longer exists")
    return brief


async def course_section(
    bindings: LateBindings, ctx: ToolContext, section_id: str
) -> tuple[CourseBrief, CourseSectionBrief]:
    """Return the outline and the section with this id, or fail."""
    brief = await course_brief(bindings, ctx)
    for section in brief.sections:
        if section.section_id == section_id:
            return brief, section
    raise ToolFailedError(
        support_details="section not found in this course: use a section id from "
        "the course outline"
    )


async def append_block(
    bindings: LateBindings, ctx: ToolContext, step_id: UUID, block: dict[str, Any]
) -> dict[str, Any]:
    """Add a block at the end of the step's draft; return where it landed."""
    draft = await course_step(bindings, ctx, step_id)
    blocks = [*draft_blocks(draft), block]
    content = {"title": step_title(draft), "blocks": blocks}
    done = await lms_call(
        workspace_commands_of(bindings).replace_step(
            ctx.actor,
            step_id,
            content,
            int(draft.get("lock_version") or 0),
            via_ai=True,
        )
    )
    return {
        "step_id": str(step_id),
        "title": content["title"],
        "block": len(blocks),
        "blocks_total": len(blocks),
        "lock_version": done.get("lock_version"),
    }
