"""LMS Course tool `create_course`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.errors import McpCourseNotAllowedError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import allowed_courses
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import Field

SCOPE = COURSES_WRITE

COURSE_ID = Annotated[UUID, Field(description="Course id from list_courses.")]


def register(kit: ToolKit) -> None:
    """Register `create_course`."""

    @kit.tool(SCOPE, read_only=False)
    async def create_course(
        title: Annotated[
            str, Field(min_length=1, max_length=200, description="Course title.")
        ],
        slug: Annotated[
            str | None,
            Field(
                default=None,
                pattern=r"^[a-z0-9-]{3,60}$",
                description="URL name (a-z, 0-9, -), made from the title if omitted.",
            ),
        ] = None,
        visibility: Annotated[
            str,
            Field(
                pattern=r"^(public|invite)$",
                description="public: anyone may enroll; invite: by invite code.",
            ),
        ] = "invite",
    ) -> dict[str, Any]:
        """Create an empty course (draft only; students see nothing until publishing).

        Needs the LMS admin or course creator role. The new course is not available
        to a connector that is limited to chosen courses.
        """
        actor = current_actor()
        if await allowed_courses(kit, actor) is not None:
            raise McpCourseNotAllowedError()
        return await kit.deps.lms_commands.create_course(
            actor, title=title, slug=slug, visibility=visibility
        )
