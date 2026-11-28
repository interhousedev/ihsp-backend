"""Students tools `list_my_ai_reviews` and `get_my_ai_review` (D4).

Only the session status and the final verdict; never the chat transcript or the
student's files. Verdict text is written by a model from student work: untrusted.
"""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.tools.learning_record import SCOPE, learning
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

VERDICT_FIELDS = (
    "summary",
    "scores[].name",
    "scores[].score",
    "scores[].comment",
    "strengths[]",
    "improvements[]",
)


def register(kit: ToolKit) -> None:
    """Register `list_my_ai_reviews` and `get_my_ai_review`."""

    @kit.tool(SCOPE)
    async def list_my_ai_reviews(
        course_id: Annotated[
            UUID | None, Field(description="Only reviews of this course.")
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most reviews to return, 1 to 50.")
        ] = 20,
    ) -> dict[str, Any]:
        """List the student's AI reviews of submitted work, newest first."""
        actor = current_actor()
        rows = await learning(kit).my_ai_reviews(
            actor, course_id=course_id, limit=limit
        )
        return mark_untrusted({"reviews": rows}, "reviews[].step_title")

    @kit.tool(SCOPE)
    async def get_my_ai_review(
        session_id: Annotated[UUID, Field(description="Id from list_my_ai_reviews.")],
    ) -> dict[str, Any]:
        """Show the final verdict of an AI review: summary, criteria, advice.

        Empty until the work has been reviewed (`reviewed` is false).
        """
        actor = current_actor()
        verdict = await learning(kit).my_ai_review(actor, session_id)
        return mark_untrusted(verdict, *VERDICT_FIELDS)
