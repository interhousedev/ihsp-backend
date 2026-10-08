"""Students tool `get_my_subjects`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import SemesterParam
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "schedule:read"


def register(kit: ToolKit) -> None:
    """Register `get_my_subjects`."""

    @kit.tool(SCOPE)
    async def get_my_subjects(semester: SemesterParam = None) -> dict[str, Any]:
        """List the student's subjects of a semester with their standing.

        Each subject has teachers, the semester mark, the EMIS rating, the number
        of absences and the number of lessons with attendance.
        """
        actor = current_actor()
        subjects = await kit.deps.marks.subjects_summary(actor.user_id, semester)
        return {"subjects": subjects}
