"""Tool: materials and attachments of a lesson (names and links, no file text)."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import ScheduleQueries


class GetLessonMaterialsArgs(ToolArgs):
    """A lesson."""

    lesson_id: UUID


class GetLessonMaterials(ReadTool[GetLessonMaterialsArgs]):
    """Materials, attachments and homework links of a lesson."""

    name = "get_lesson_materials"
    description = (
        "Materials and attachments of a lesson: title, kind, role, file id or URL. "
        "It does not return file text; use read_file with the file id for that."
    )
    args_model = GetLessonMaterialsArgs

    def __init__(self, schedule: ScheduleQueries, bindings: LateBindings) -> None:
        """Store the schedule queries and the late-bound links API."""
        self.schedule = schedule
        self.bindings = bindings

    async def run(
        self, args: GetLessonMaterialsArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the visible resources of a lesson the student attends."""
        links = self.bindings.links
        if links is None:
            raise ToolFailedError(support_details="lesson materials are unavailable")
        if not await self.schedule.is_in_audience(ctx.actor.user_id, args.lesson_id):
            raise ToolFailedError(support_details="lesson not found")
        resources = await links.lesson_resources(args.lesson_id)
        return {
            "lesson_id": str(args.lesson_id),
            "resources": [
                {
                    "link_id": str(r.link_id),
                    "role": r.role,
                    "kind": r.kind,
                    "title": r.title,
                    "url": r.short_url,
                    "file_id": str(r.file_id) if r.file_id else None,
                    "added_by": r.author_first_name,
                }
                for r in resources
            ],
        }
