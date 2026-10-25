"""Students tool `get_lesson_materials`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.errors import McpNotFoundError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "materials:read"


def register(kit: ToolKit) -> None:
    """Register `get_lesson_materials`."""

    @kit.tool(SCOPE)
    async def get_lesson_materials(
        lesson_id: Annotated[UUID, Field(description="Lesson id from get_schedule.")],
    ) -> dict[str, Any]:
        """List the materials and attachments of one of the student's lessons.

        Each item has a title, kind (url or file), role (material or attachment),
        a short link and, for files, a file_id. File text is not included: pass
        the file_id and this lesson_id to read_file.
        """
        actor = current_actor()
        deps = kit.deps
        lesson = await deps.schedule.get_lesson(lesson_id)
        if lesson is None or not await deps.schedule.is_in_audience(
            actor.user_id, lesson_id
        ):
            raise McpNotFoundError()
        resources = await deps.links.lesson_resources(lesson_id)
        return {
            "lesson_id": lesson_id,
            "subject_name": lesson.subject_name,
            "resources": [
                {
                    "link_id": item.link_id,
                    "role": item.role,
                    "kind": item.kind,
                    "title": item.title,
                    "short_url": item.short_url,
                    "file_id": item.file_id,
                    "author": item.author_first_name,
                }
                for item in resources
            ],
        }
