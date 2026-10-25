"""Tool: the student's own absences."""

import datetime as dt
from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped, lesson_dict
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import ClassworkQueries

from pydantic import Field


class GetAttendanceArgs(ToolArgs):
    """Optional date range."""

    date_from: dt.date | None = Field(default=None, alias="from")
    date_to: dt.date | None = Field(default=None, alias="to")


class GetAttendance(ReadTool[GetAttendanceArgs]):
    """The student's absences."""

    name = "get_attendance"
    description = (
        "The student's absences in a date range (YYYY-MM-DD), each with the "
        "lesson and whether it was excused."
    )
    args_model = GetAttendanceArgs

    def __init__(self, classwork: ClassworkQueries) -> None:
        """Store the classwork queries."""
        self.classwork = classwork

    async def run(self, args: GetAttendanceArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return absences."""
        items = await self.classwork.absences(
            ctx.actor.user_id, args.date_from, args.date_to
        )
        rows = []
        for item in items:
            row = lesson_dict(item["lesson"])
            row["excused"] = bool(item["excused"])
            rows.append(row)
        return capped(rows)
