"""Tool: the student's subjects of the current semester."""

from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import MarksQueries


class GetMySubjectsArgs(ToolArgs):
    """No arguments."""


class GetMySubjects(ReadTool[GetMySubjectsArgs]):
    """Subjects with teachers, semester mark, EMIS rating and absences."""

    name = "get_my_subjects"
    description = (
        "List the student's subjects of the current semester with teachers, "
        "semester mark, EMIS rating and absences."
    )
    args_model = GetMySubjectsArgs

    def __init__(self, marks: MarksQueries) -> None:
        """Store the marks queries."""
        self.marks = marks

    async def run(self, args: GetMySubjectsArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the subjects summary."""
        rows = await self.marks.subjects_summary(ctx.actor.user_id, None)
        return {
            "subjects": [
                {
                    "subject_id": str(row.subject_id),
                    "name": row.name,
                    "teachers": list(row.teacher_names),
                    "semester_mark": row.semester_mark,
                    "emis_rating": row.emis_rating,
                    "absences": row.absences,
                    "lessons_with_attendance": row.lessons_with_attendance,
                }
                for row in rows
            ]
        }
