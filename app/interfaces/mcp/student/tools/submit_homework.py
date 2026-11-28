"""Students tools `submit_homework` and `withdraw_homework_submission`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "homework:submit"

LessonIdParam = Annotated[UUID, Field(description="The lesson with the homework.")]


def register(kit: ToolKit) -> None:
    """Register the homework submission tools."""

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id",)),
    )
    async def submit_homework(
        lesson_id: LessonIdParam,
        file_ids: Annotated[
            list[UUID],
            Field(
                max_length=10,
                description="Ready files of the student (see upload_file); optional.",
            ),
        ] = [],  # noqa: B006 - pydantic copies the default
        comment: Annotated[
            str | None, Field(max_length=2000, description="Optional note.")
        ] = None,
        text: Annotated[
            str | None,
            Field(max_length=10000, description="The answer as text; optional."),
        ] = None,
    ) -> dict[str, Any]:
        """Hand in (or replace) the student's submission for a lesson's homework.

        Give text, files or both. Upload files first with upload_file. After the
        due date the submission counts as late; a graded submission is final.
        """
        answer = text.strip() if text is not None else None
        return await kit.deps.academic_tools.submit_homework(
            current_actor(), lesson_id, file_ids, comment, answer or None
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id",)),
    )
    async def withdraw_homework_submission(lesson_id: LessonIdParam) -> dict[str, Any]:
        """Withdraw the student's submission for a lesson's homework."""
        await kit.deps.academic_tools.withdraw_homework_submission(
            current_actor(), lesson_id
        )
        return {"withdrawn": True}
