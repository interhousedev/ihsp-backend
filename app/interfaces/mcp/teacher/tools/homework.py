"""Teacher homework tools: the board, the assignment, its switches and defaults."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted

from pydantic import Field

SCOPE = "homework:write"
READ_SCOPE = "homework:read"

LessonIdParam = Annotated[
    UUID, Field(description="A lesson the teacher teaches (id from the timetable).")
]
NotifyChoice = Literal["on", "off", "teacher_default"]
_NOTIFY: dict[str, bool | None] = {"on": True, "off": False, "teacher_default": None}


def register(kit: ToolKit) -> None:
    """Register the homework tools."""

    @kit.tool(READ_SCOPE)
    async def list_homework_lessons(
        subject_id: Annotated[
            UUID, Field(description="Subject of a journal (from list_my_groups).")
        ],
        audience_key: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Audience of the journal (from list_my_groups).",
            ),
        ],
        date_from: Annotated[
            date | None, Field(description="First day, YYYY-MM-DD; default term.")
        ] = None,
        date_to: Annotated[
            date | None, Field(description="Last day, YYYY-MM-DD; default term.")
        ] = None,
        only: Annotated[
            Literal["all", "with_homework", "to_review"],
            Field(description="Filter: all lessons, with homework, or to review."),
        ] = "all",
    ) -> dict[str, Any]:
        """The homework board of a journal the teacher teaches, newest first.

        Each lesson has its EMIS topic, EMIS homework files, the homework, the
        switches (accept submissions, notify) and submission counts.
        """
        board = await kit.deps.teacher_tools.homework_board(
            current_actor(), subject_id, audience_key, date_from, date_to, only
        )
        return mark_untrusted(
            board,
            "lessons[].topic",
            "lessons[].emis_topic_description",
            "lessons[].emis_files[].title",
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id", "due_date", "accept_submissions")),
    )
    async def set_homework(
        lesson_id: LessonIdParam,
        text: Annotated[
            str | None,
            Field(
                max_length=4000,
                description=(
                    "The assignment; may be omitted when the lesson already has "
                    "EMIS homework."
                ),
            ),
        ] = None,
        due_date: Annotated[
            date | None, Field(description="Due date, YYYY-MM-DD; optional.")
        ] = None,
        accept_submissions: Annotated[
            bool | None,
            Field(description="Accept submissions on my.iht; omit to keep."),
        ] = None,
    ) -> dict[str, Any]:
        """Set (replace) the homework of one of the teacher's lessons."""
        cleaned = text.strip() if text is not None else None
        return await kit.deps.teacher_tools.set_homework(
            current_actor(), lesson_id, cleaned or None, due_date, accept_submissions
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id", "accept_submissions", "notify")),
    )
    async def set_homework_settings(
        lesson_id: LessonIdParam,
        accept_submissions: Annotated[
            bool | None,
            Field(description="Accept submissions for this lesson; omit to keep."),
        ] = None,
        notify: Annotated[
            NotifyChoice | None,
            Field(
                description=(
                    "Notify me of submissions: on, off, or teacher_default to "
                    "follow my preferences; omit to keep."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Change the homework switches of one of the teacher's lessons."""
        return await kit.deps.teacher_tools.set_homework_switches(
            current_actor(),
            lesson_id,
            accept_submissions,
            _NOTIFY[notify] if notify is not None else None,
            notify is not None,
        )

    @kit.tool(READ_SCOPE)
    async def get_homework_preferences() -> dict[str, Any]:
        """The teacher's homework defaults: accept by default, notify on submission."""
        return await kit.deps.teacher_tools.homework_preferences(current_actor())

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("accept_by_default", "notify_on_submission")),
    )
    async def set_homework_preferences(
        accept_by_default: Annotated[
            bool | None,
            Field(description="New homework accepts submissions; omit to keep."),
        ] = None,
        notify_on_submission: Annotated[
            bool | None,
            Field(description="Notify me when a student submits; omit to keep."),
        ] = None,
    ) -> dict[str, Any]:
        """Change the teacher's own homework defaults."""
        return await kit.deps.teacher_tools.save_homework_preferences(
            current_actor(), accept_by_default, notify_on_submission
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        destructive=True,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("lesson_id",)),
    )
    async def clear_homework(lesson_id: LessonIdParam) -> dict[str, Any]:
        """Remove the homework of one of the teacher's lessons."""
        return await kit.deps.teacher_tools.clear_homework(current_actor(), lesson_id)
