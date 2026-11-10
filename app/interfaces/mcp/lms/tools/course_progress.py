"""LMS Course tool `course_progress`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.lms_scopes import COURSES_READ

from pydantic import Field

SCOPE = COURSES_READ


def register(kit: ToolKit) -> None:
    """Register `course_progress`."""

    @kit.tool(SCOPE)
    async def course_progress(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
    ) -> dict[str, Any]:
        """Summarise a course: students with progress and the latest attempts.

        This is the only analytics available; there are no per-question statistics.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        students = await kit.deps.lms_ops.students(actor, course_id)
        attempts = await kit.deps.lms_queries.attempts(course_id, actor, 20)
        return {
            "student_count": len(students),
            "students": students,
            "latest_attempts": attempts,
        }
