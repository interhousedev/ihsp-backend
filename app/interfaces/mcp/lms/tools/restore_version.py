"""LMS Course tool `restore_version`."""

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
    """Register `restore_version`."""

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("course_id", "number")))
    async def restore_version(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        number: Annotated[
            int, Field(ge=1, description="Version number from list_versions.")
        ],
    ) -> dict[str, Any]:
        """Copy an earlier published version into the draft.

        Publish afterwards to apply it.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        result = await kit.deps.lms_ops.restore_version(actor, course_id, number)
        return result if isinstance(result, dict) else {"items": result}
