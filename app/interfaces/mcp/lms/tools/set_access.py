"""LMS Course tool `set_access`."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.modules.lms.domain.access_rules import MAX_CHOSEN
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import Field

SCOPE = COURSES_WRITE


def register(kit: ToolKit) -> None:
    """Register `set_access`."""

    @kit.tool(
        SCOPE,
        read_only=False,
        log=LogSpec(keep=("course_id", "step_id")),
    )
    async def set_access(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        audience: Annotated[
            Literal["public", "signed_in", "students", "chosen"],
            Field(
                description=(
                    "public: everyone, guests too; signed_in: any signed-in user; "
                    "students: lyceum students; chosen: the listed groups and users."
                ),
            ),
        ],
        step_id: Annotated[
            UUID | None,
            Field(default=None, description="Lesson id; omit to set the course."),
        ] = None,
        when_denied: Annotated[
            Literal["hidden", "locked"],
            Field(description="hidden: looks missing; locked: listed with a lock."),
        ] = "hidden",
        group_ids: Annotated[
            list[UUID],
            Field(max_length=MAX_CHOSEN, description="Groups, for chosen."),
        ] = [],  # noqa: B006
        user_ids: Annotated[
            list[UUID],
            Field(max_length=MAX_CHOSEN, description="Users, for chosen."),
        ] = [],  # noqa: B006
    ) -> dict[str, Any]:
        """Set who may open a course or a lesson; the owner or an LMS admin only."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_ops.set_access(
            actor,
            course_id,
            step_id=step_id,
            audience=audience,
            when_denied=when_denied,
            group_ids=group_ids,
            user_ids=user_ids,
        )
