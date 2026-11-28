"""LMS Course tool `list_ai_review_submissions`: AI-review verdicts of one block."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.not_wired import NotWired
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `list_ai_review_submissions`."""

    @kit.tool(SCOPE)
    async def list_ai_review_submissions(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
        block_id: Annotated[
            str,
            Field(min_length=1, max_length=64, description="AI review block id."),
        ],
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most submissions, 1 to 50.")
        ] = 50,
    ) -> dict[str, Any]:
        """List the students' AI-review submissions of a block with each verdict.

        Needs the review permission on the course. Only the verdict (summary,
        criteria, strengths, improvements), never the chat or the students' files.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        backend = kit.deps.learning_tools or NotWired("mcp_learning_tools")
        rows = await backend.ai_review_submissions(
            actor, course_id, step_id, block_id, limit=limit
        )
        return mark_untrusted(
            {"submissions": rows},
            "submissions[].summary",
            "submissions[].scores[].name",
            "submissions[].scores[].score",
            "submissions[].scores[].comment",
            "submissions[].strengths[]",
            "submissions[].improvements[]",
        )
