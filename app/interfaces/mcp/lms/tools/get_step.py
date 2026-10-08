"""LMS Course tool `get_step`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import (
    allowed_courses,
    course_id_of,
    ensure_allowed,
)
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "courses:read"


def register(kit: ToolKit) -> None:
    """Register `get_step`."""

    @kit.tool(SCOPE)
    async def get_step(
        step_id: Annotated[UUID, Field(description="Step id from get_course.")],
    ) -> dict[str, Any]:
        """Show the draft content of one step: its blocks, questions and cards."""
        actor = current_actor()
        draft = await kit.deps.lms_queries.step_draft(step_id, actor)
        ensure_allowed(await allowed_courses(kit, actor), course_id_of(draft))
        return draft
