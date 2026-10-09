"""Author tool: the draft outline of the chat's course."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorReadTool
from app.modules.ai.application.tools.lms_common import (
    lms_call,
    scope_of,
    workspace_of,
)
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs


class GetCourseOutlineArgs(ToolArgs):
    """No arguments: the course is the chat's course."""


class GetCourseOutline(AuthorReadTool[GetCourseOutlineArgs]):
    """Sections and steps of the course draft, with ids."""

    name = "get_course_outline"
    description = (
        "Read the course's draft outline: title, description, draft_seq and the "
        "sections in order (section_id, title) with their steps (step_id, title). "
        "Use it when the COURSE CONTEXT says the outline was shortened or could not "
        "be loaded. Not needed otherwise: the context is refreshed before each of "
        "your requests. No arguments; it always reads this chat's course. "
        "Example: get_course_outline {}"
    )
    args_model = GetCourseOutlineArgs

    async def run(self, args: GetCourseOutlineArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the outline of the scope's course."""
        scope = scope_of(ctx)
        brief = await lms_call(
            workspace_of(self.bindings).course_brief(scope.course_id)
        )
        if brief is None:
            raise ToolFailedError(support_details="the course no longer exists")
        return {
            "course_id": str(brief.course_id),
            "title": brief.title,
            "description": brief.description,
            "draft_seq": brief.draft_seq,
            "sections": [
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "steps": [
                        {"step_id": str(step.step_id), "title": step.title}
                        for step in section.steps
                    ],
                }
                for section in brief.sections
            ],
        }
