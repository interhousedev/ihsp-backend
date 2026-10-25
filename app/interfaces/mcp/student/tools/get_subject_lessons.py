"""Students tool `get_subject_lessons`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.student.views import lesson_view
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "schedule:read"


def register(kit: ToolKit) -> None:
    """Register `get_subject_lessons`."""

    @kit.tool(SCOPE)
    async def get_subject_lessons(
        subject_id: Annotated[
            UUID, Field(description="Subject id from get_my_subjects.")
        ],
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
    ) -> dict[str, Any]:
        """List the lessons of one subject for the student's own audience.

        Without dates all lessons of the subject are returned.
        """
        actor = current_actor()
        check_range(date_from, date_to)
        lessons = await kit.deps.classwork.subject_lessons(
            actor.user_id, subject_id, date_from, date_to
        )
        return {
            "subject_id": subject_id,
            "lessons": [lesson_view(lesson) for lesson in lessons],
        }
