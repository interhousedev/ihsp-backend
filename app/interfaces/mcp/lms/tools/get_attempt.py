"""LMS Course tool `get_attempt`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import (
    allowed_courses,
    course_id_of,
    ensure_allowed,
)
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `get_attempt`."""

    @kit.tool(SCOPE)
    async def get_attempt(
        attempt_id: Annotated[
            UUID, Field(description="Attempt id from list_attempts.")
        ],
    ) -> dict[str, Any]:
        """Read one test attempt with the answers and the score."""
        actor = current_actor()
        attempt = await kit.deps.lms_ops.attempt(actor, attempt_id)
        ensure_allowed(await allowed_courses(kit, actor), course_id_of(attempt))
        return attempt
