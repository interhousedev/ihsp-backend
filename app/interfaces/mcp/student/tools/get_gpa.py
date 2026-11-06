"""Students tool `get_gpa`."""

from typing import Any

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import SemesterParam
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "marks:read"


def register(kit: ToolKit) -> None:
    """Register `get_gpa`."""

    @kit.tool(SCOPE, log=LogSpec(keep=("semester",)))
    async def get_gpa(semester: SemesterParam = None) -> dict[str, Any]:
        """Show the student's GPA of a semester, as the platform calculates it.

        `gpa` excludes temporary marks. Per subject: the semester mark, and
        `gpa_with_temporary`, a separate value that counts them. Subjects without
        marks are left out.
        """
        actor = current_actor()
        result = await kit.deps.academic_tools.gpa(actor.user_id, semester)
        return {
            **result,
            "calculated_by": "platform",
            "subjects": [row for row in result["subjects"] if row["marks_count"]],
        }
