"""Students tool `get_results`."""

from typing import Any

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import SemesterParam
from app.interfaces.mcp.toolkit import ToolKit

SCOPE = "marks:read"


def register(kit: ToolKit) -> None:
    """Register `get_results`."""

    @kit.tool(SCOPE)
    async def get_results(semester: SemesterParam = None) -> dict[str, Any]:
        """Show the student's semester results.

        Includes the GPA and, per subject, the lesson, midterm and final averages,
        the semester mark and the EMIS rating. Subjects without marks are left out.
        """
        actor = current_actor()
        results = await kit.deps.marks.results(actor.user_id, semester)
        return {
            **results,
            "subjects": [
                subject for subject in results["subjects"] if subject["marks_count"]
            ],
        }
