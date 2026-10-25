"""LMS Course tool `delete_course`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_DELETE

from pydantic import Field

SCOPE = COURSES_DELETE

COURSE_ID = Annotated[UUID, Field(description="Course id from list_courses.")]


def register(kit: ToolKit) -> None:
    """Register `delete_course`."""

    @kit.tool(SCOPE, read_only=False, destructive=True)
    async def delete_course(course_id: COURSE_ID) -> dict[str, Any]:
        """Delete a course: it is archived and closed to students.

        The content, the versions and the attempts are kept, so a person with access
        to the database can restore it. Needs the course owner or an LMS admin.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_commands.delete_course(actor, course_id)
