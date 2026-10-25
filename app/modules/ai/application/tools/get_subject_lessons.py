"""Tool: lessons of one subject with marks and absences."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import MAX_ROWS, lesson_dict
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import ClassworkQueries, MarksQueries

from pydantic import Field


class GetSubjectLessonsArgs(ToolArgs):
    """A subject and an optional date range."""

    subject_id: UUID
    date_from: dt.date | None = Field(default=None, alias="from")
    date_to: dt.date | None = Field(default=None, alias="to")


class GetSubjectLessons(ReadTool[GetSubjectLessonsArgs]):
    """Lessons of a subject for the student's audience."""

    name = "get_subject_lessons"
    description = (
        "Lessons of one subject for the student: date, period, topic, homework, "
        "the student's marks and absences. Dates are optional (YYYY-MM-DD)."
    )
    args_model = GetSubjectLessonsArgs

    def __init__(self, classwork: ClassworkQueries, marks: MarksQueries) -> None:
        """Store the classwork and marks queries."""
        self.classwork = classwork
        self.marks = marks

    async def run(
        self, args: GetSubjectLessonsArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the lessons with their marks and absence state."""
        user = ctx.actor.user_id
        start, end = args.date_from, args.date_to
        lessons = await self.classwork.subject_lessons(
            user, args.subject_id, start, end
        )
        marks = await self.marks.marks(user, args.subject_id, start, end)
        absences = await self.classwork.absences(user, start, end)
        absent = {item["lesson"].id: item["excused"] for item in absences}
        rows = []
        for lesson in lessons[-MAX_ROWS:]:
            row = lesson_dict(lesson)
            row["marks"] = [m.value for m in marks if m.lesson_id == lesson.id]
            row["absence"] = _absence(absent.get(lesson.id))
            rows.append(row)
        return {"lessons": rows, "truncated": len(lessons) > MAX_ROWS}


def _absence(excused: bool | None) -> str | None:
    if excused is None:
        return None
    return "excused" if excused else "absent"
