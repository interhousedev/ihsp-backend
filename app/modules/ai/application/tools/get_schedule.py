"""Tool: the student's lessons in a date range."""

import datetime as dt
from typing import Any

from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped, lesson_dict
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.shared.contracts.academic import ScheduleQueries

from pydantic import Field

MAX_DAYS = 62


class GetScheduleArgs(ToolArgs):
    """A date range."""

    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")


class GetSchedule(ReadTool[GetScheduleArgs]):
    """The student's lessons between two dates."""

    name = "get_schedule"
    description = (
        f"The student's lessons between two dates (YYYY-MM-DD), at most {MAX_DAYS} "
        "days: time, subject, room, topic and homework."
    )
    args_model = GetScheduleArgs

    def __init__(self, schedule: ScheduleQueries) -> None:
        """Store the schedule queries."""
        self.schedule = schedule

    async def validate(self, args: GetScheduleArgs, ctx: ToolContext) -> None:
        """Reject reversed or too long ranges."""
        span = (args.date_to - args.date_from).days
        if span < 0 or span > MAX_DAYS:
            raise ToolFailedError(
                support_details=f"the range must be 0-{MAX_DAYS} days and not reversed"
            )

    async def run(self, args: GetScheduleArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return lessons, including ones projected beyond the generation horizon."""
        await self.validate(args, ctx)
        lessons = await self.schedule.projected_lessons_for_student(
            ctx.actor.user_id, args.date_from, args.date_to
        )
        return capped([lesson_dict(lesson) for lesson in lessons])
