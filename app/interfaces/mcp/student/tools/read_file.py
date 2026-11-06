"""Students tool `read_file`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.errors import (
    McpFileAccessError,
    McpFileNoTextError,
    McpFileTooLargeError,
)
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.shared.actor import Actor
from app.shared.contracts.files import FileRef

from pydantic import Field

SCOPE = "files:read"
WIDE_SCOPE = "files:read.all"


async def _origin_of(
    kit: ToolKit, actor: Actor, file: FileRef, lesson_id: UUID | None
) -> str | None:
    """Why the student may read the file; None when they may not."""
    if file.owner_id == actor.user_id:
        return "personal"
    deps = kit.deps
    if (
        lesson_id is not None
        and await deps.schedule.is_in_audience(actor.user_id, lesson_id)
        and any(
            item.file_id == file.id
            for item in await deps.links.lesson_resources(lesson_id)
        )
    ):
        return "lesson"
    if not await kit.guard.has_scope(actor, WIDE_SCOPE):
        return None
    visible = await deps.files_courses_tools.resolve_file(actor, file.id)
    return None if visible is None else visible.origin


def register(kit: ToolKit) -> None:
    """Register `read_file`."""

    @kit.tool(SCOPE, log=LogSpec(keep=("file_id", "page", "lesson_id")))
    async def read_file(
        file_id: Annotated[UUID, Field(description="File id from list_files.")],
        page: Annotated[int, Field(ge=1, description="Page number, from 1.")] = 1,
        lesson_id: Annotated[
            UUID | None,
            Field(
                description="Lesson the file is attached to, from get_lesson_materials."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Read one page (up to 8 KB) of a file's extracted text.

        Works for the student's own files, for files attached to the student's lessons
        (pass lesson_id) and, with `files:read.all`, for anything list_files shows.
        `pages` tells how many pages the file has.
        """
        actor = current_actor()
        deps = kit.deps
        file = await deps.files.get(file_id)
        if file is None or file.status != "ready":
            raise McpFileAccessError()
        origin = await _origin_of(kit, actor, file, lesson_id)
        if origin is None:
            raise McpFileAccessError()
        if file.text_bytes is None:
            raise McpFileNoTextError()
        limit = deps.settings.limits.ai_text_max_bytes
        if file.text_bytes > limit:
            raise McpFileTooLargeError(params={"max_bytes": limit})
        text_page = await deps.files.read_text_page(file_id, page)
        return mark_untrusted(
            {
                "file_id": file_id,
                "name": file.name,
                "origin": origin,
                "page": text_page.page,
                "pages": text_page.pages,
                "text": text_page.text,
            },
            "name",
            "text",
        )
