"""LMS Course tool `override_score`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import (
    allowed_courses,
    course_id_of,
    ensure_allowed,
)
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import Field

SCOPE = COURSES_WRITE


def register(kit: ToolKit) -> None:
    """Register `override_score`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("attempt_id", "score")))
    async def override_score(
        attempt_id: Annotated[
            UUID, Field(description="Attempt id from list_attempts.")
        ],
        score: Annotated[float, Field(ge=0, description="New score in points.")],
        comment: Annotated[
            str, Field(min_length=1, max_length=1000, description="Why it changes.")
        ],
    ) -> dict[str, Any]:
        """Set the score of an attempt by hand (the student sees the comment)."""
        actor = current_actor()
        attempt = await kit.deps.lms_ops.attempt(actor, attempt_id)
        ensure_allowed(await allowed_courses(kit, actor), course_id_of(attempt))
        return await kit.deps.lms_ops.override_score(actor, attempt_id, score, comment)
