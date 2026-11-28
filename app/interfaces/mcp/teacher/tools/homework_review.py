"""Teacher tools for homework submissions: list, read, review, clear the review.

Student text, comments and file names are untrusted: they are cleaned and listed in
`untrusted_fields` so the model treats them as data, never as instructions.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

READ_SCOPE = "homework:read"
SCOPE = "homework:review"

_ROW_FIELDS = ("text", "comment", "previous_comment", "files[].name")

SubmissionIdParam = Annotated[
    UUID, Field(description="A submission id (from list_homework_submissions).")
]


def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return mark_untrusted(row, *_ROW_FIELDS)


def register(kit: ToolKit) -> None:
    """Register the submission review tools."""

    @kit.tool(READ_SCOPE)
    async def list_homework_submissions(
        lesson_id: Annotated[UUID, Field(description="A lesson the teacher teaches.")],
    ) -> dict[str, Any]:
        """Who handed in the homework of one of the teacher's lessons.

        Every student of the group has a status (submitted, late, missing) and a
        review state (pending, returned, graded); files carry a time-limited
        `download_url`.
        """
        result = await kit.deps.teacher_tools.homework_submissions(
            current_actor(), lesson_id
        )
        return mark_untrusted(result, *(f"students[].{p}" for p in _ROW_FIELDS))

    @kit.tool(READ_SCOPE)
    async def get_homework_submission(
        submission_id: SubmissionIdParam,
    ) -> dict[str, Any]:
        """One submission: the student's text, files with download links, review."""
        row = await kit.deps.teacher_tools.homework_submission(
            current_actor(), submission_id
        )
        return _clean_row(row)

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("submission_id", "action", "grade")),
    )
    async def review_homework_submission(
        submission_id: SubmissionIdParam,
        action: Annotated[
            Literal["grade", "return"],
            Field(description="grade: give a mark; return: send back for rework."),
        ],
        grade: Annotated[
            int | None,
            Field(ge=2, le=5, description="Mark 2..5; required for grade."),
        ] = None,
        comment: Annotated[
            str | None,
            Field(
                max_length=2000,
                description="Comment for the student; required for return.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Grade or return a submission; the student is notified.

        A grade also writes the lesson's temporary mark of the student.
        """
        text = comment.strip() if comment is not None else None
        row = await kit.deps.teacher_tools.review_homework_submission(
            current_actor(), submission_id, action, grade, text or None
        )
        return _clean_row(row)

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("submission_id",)),
    )
    async def clear_homework_review(submission_id: SubmissionIdParam) -> dict[str, Any]:
        """Remove the grade and comment; the submission is pending again."""
        await kit.deps.teacher_tools.clear_homework_review(
            current_actor(), submission_id
        )
        return {"submission_id": str(submission_id), "review_status": "pending"}
