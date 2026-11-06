"""Students tool `get_my_teachers`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "teachers:read"


def register(kit: ToolKit) -> None:
    """Register `get_my_teachers`."""

    @kit.tool(SCOPE)
    async def get_my_teachers() -> dict[str, Any]:
        """List the teachers of the student's group, with subjects and next lesson.

        Contacts appear only where the teacher chose to show them to students.
        """
        actor = current_actor()
        teachers = await kit.deps.academic_tools.my_teachers(actor)
        return {
            "teachers": [
                {**teacher, "links": kit.deps.web_links.teacher(teacher["id"])}
                for teacher in teachers
            ]
        }
