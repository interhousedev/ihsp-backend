"""Tool: homework with its done state."""

import datetime as dt
from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped, lesson_dict
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import ClassworkQueries

from pydantic import Field


class GetHomeworkArgs(ToolArgs):
    """Optional date range and done filter."""

    date_from: dt.date | None = Field(default=None, alias="from")
    date_to: dt.date | None = Field(default=None, alias="to")
    done: bool | None = None


class GetHomework(ReadTool[GetHomeworkArgs]):
    """The student's homework."""

    name = "get_homework"
    description = (
        "The student's homework with the lesson, due date, done state and the "
        "student's own note. Filter by dates (YYYY-MM-DD) and done."
    )
    args_model = GetHomeworkArgs

    def __init__(self, classwork: ClassworkQueries) -> None:
        """Store the classwork queries."""
        self.classwork = classwork

    async def run(self, args: GetHomeworkArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return homework items."""
        items = await self.classwork.homework(
            ctx.actor.user_id, args.date_from, args.date_to, args.done
        )
        rows = []
        for item in items:
            row = lesson_dict(item["lesson"])
            row["done_at"] = _stamp(item.get("done_at"))
            row["note"] = item.get("note")
            rows.append(row)
        return capped(rows)


def _stamp(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
