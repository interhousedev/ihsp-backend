"""Students tool `read_file`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.errors import (
    McpFileAccessError,
    McpFileNoTextError,
    McpFileTooLargeError,
)
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.actor import Actor
from app.shared.contracts.files import FileRef

from pydantic import Field

SCOPE = "files:read"


async def _may_read(
    kit: ToolKit, actor: Actor, file: FileRef, lesson_id: UUID | None
) -> bool:
    """A file is readable by its owner or through a lesson the student attends."""
    if file.owner_id == actor.user_id:
        return True
    if lesson_id is None:
        return False
    deps = kit.deps
    if not await deps.schedule.is_in_audience(actor.user_id, lesson_id):
        return False
    resources = await deps.links.lesson_resources(lesson_id)
    return any(item.file_id == file.id for item in resources)


def register(kit: ToolKit) -> None:
    """Register `read_file`."""

    @kit.tool(SCOPE)
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

        Works for the student's own files and for files attached to the student's
        lessons (pass lesson_id). `pages` tells how many pages the file has.
        """
        actor = current_actor()
        deps = kit.deps
        file = await deps.files.get(file_id)
        if file is None or file.status != "ready":
            raise McpFileAccessError()
        if not await _may_read(kit, actor, file, lesson_id):
            raise McpFileAccessError()
        if file.text_bytes is None:
            raise McpFileNoTextError()
        limit = deps.settings.limits.ai_text_max_bytes
        if file.text_bytes > limit:
            raise McpFileTooLargeError(params={"max_bytes": limit})
        text_page = await deps.files.read_text_page(file_id, page)
        return {
            "file_id": file_id,
            "name": file.name,
            "page": text_page.page,
            "pages": text_page.pages,
            "text": text_page.text,
        }
