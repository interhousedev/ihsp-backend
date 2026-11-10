"""LMS Course tool `update_settings`."""

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
    """Register `update_settings`."""

    @kit.tool(
        SCOPE,
        read_only=False,
        log=LogSpec(keep=("course_id", "cover_file_id", "clear_cover")),
    )
    async def update_settings(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        visibility: Annotated[
            str | None,
            Field(
                default=None,
                pattern=r"^(public|invite)$",
                description="public: anyone may enroll; invite: by invite code.",
            ),
        ] = None,
        cover_file_id: Annotated[
            UUID | None,
            Field(default=None, description="File id of an uploaded cover image."),
        ] = None,
        clear_cover: Annotated[
            bool, Field(description="True removes the cover.")
        ] = False,
    ) -> dict[str, Any]:
        """Change course visibility and cover; omitted fields stay as they are."""
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        return await kit.deps.lms_ops.update_settings(
            actor,
            course_id,
            visibility=visibility,
            cover_file_id=cover_file_id,
            clear_cover=clear_cover,
        )
