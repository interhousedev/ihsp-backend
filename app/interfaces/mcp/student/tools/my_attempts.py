"""Students tools `list_my_attempts` and `get_my_attempt` (anti-cheating rule D2).

Only submitted attempts are listed; open exam sittings never are. Per-question
correctness is shown for a submitted attempt; prompts, explanations and correct
answers only when the step's answers policy already shows them on the web.
"""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.student.tools.learning_record import SCOPE, learning
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field


def register(kit: ToolKit) -> None:
    """Register `list_my_attempts` and `get_my_attempt`."""

    @kit.tool(SCOPE)
    async def list_my_attempts(
        course_id: Annotated[
            UUID, Field(description="Course id from get_learning_record.")
        ],
        step_id: Annotated[
            UUID | None, Field(description="Only attempts of this step.")
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=50, description="Most attempts to return, 1 to 50.")
        ] = 20,
        cursor: Annotated[
            str | None, Field(description="`next_cursor` of the previous page.")
        ] = None,
    ) -> dict[str, Any]:
        """List the student's submitted test attempts in a course, newest first.

        Each: step and section, attempt number, score, max score, passed, date.
        """
        actor = current_actor()
        page = await learning(kit).my_attempts(
            actor, course_id, step_id=step_id, limit=limit, cursor=cursor
        )
        return mark_untrusted(page, "attempts[].step_title", "attempts[].section_title")

    @kit.tool(SCOPE)
    async def get_my_attempt(
        attempt_id: Annotated[UUID, Field(description="Id from list_my_attempts.")],
    ) -> dict[str, Any]:
        """Show one submitted attempt: score, totals per question type, questions.

        `review_shown` says whether the course shows answers for this step; when
        false, questions carry only type, points and correctness, without the prompt,
        explanation or correct answer.
        """
        actor = current_actor()
        view = await learning(kit).my_attempt(actor, attempt_id)
        return mark_untrusted(view, "questions[].prompt", "questions[].explanation")
