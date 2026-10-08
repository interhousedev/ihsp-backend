"""Tool: the student's marks."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped, mark_dict
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import MarksQueries

from pydantic import Field


class GetMarksArgs(ToolArgs):
    """Optional subject and date range."""

    subject_id: UUID | None = None
    date_from: dt.date | None = Field(default=None, alias="from")
    date_to: dt.date | None = Field(default=None, alias="to")


class GetMarks(ReadTool[GetMarksArgs]):
    """The student's marks."""

    name = "get_marks"
    description = (
        "The student's marks (lesson, midterm, final) with subject, date and "
        "semester. Filter by subject and dates (YYYY-MM-DD)."
    )
    args_model = GetMarksArgs

    def __init__(self, marks: MarksQueries) -> None:
        """Store the marks queries."""
        self.marks = marks

    async def run(self, args: GetMarksArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return marks, newest last."""
        rows = await self.marks.marks(
            ctx.actor.user_id, args.subject_id, args.date_from, args.date_to
        )
        return capped([mark_dict(row) for row in rows])
