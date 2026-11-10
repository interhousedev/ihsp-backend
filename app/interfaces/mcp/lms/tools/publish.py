"""LMS Course tool `publish`."""

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
    """Register `publish`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("course_id",)))
    async def publish(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        note: Annotated[
            str | None, Field(default=None, max_length=500, description="Version note.")
        ] = None,
    ) -> dict[str, Any]:
        """Publish the draft as a new version; students then see it.

        There is no unpublish: to hide a course use delete_course (archive) or
        restore_version to an earlier version and publish again. Check
        list_pending_changes first.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.publish(actor, course_id, note)
        return result if isinstance(result, dict) else {"items": result}
