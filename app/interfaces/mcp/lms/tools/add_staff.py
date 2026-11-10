"""LMS Course tool `add_staff`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_WRITE

from pydantic import Field

SCOPE = COURSES_WRITE


def register(kit: ToolKit) -> None:
    """Register `add_staff`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("course_id",)))
    async def add_staff(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        login: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="Login of an existing platform user.",
            ),
        ],
        role: Annotated[
            str,
            Field(
                min_length=1,
                max_length=50,
                description="Role label or preset (e.g. teacher, assistant).",
            ),
        ],
        permissions: Annotated[
            list[str] | None,
            Field(
                default=None,
                description="Explicit permissions; omit to use the preset of the role.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Add a platform user (found by login) to the course staff.

        Students are enrolled by invite code, not with this tool (no staff
        enrollment of students).
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.add_staff(
            actor, course_id, login=login, role=role, permissions=permissions
        )
        return result if isinstance(result, dict) else {"items": result}
