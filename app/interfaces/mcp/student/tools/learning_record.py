"""Student tools of the learning record: summary, course progress, certificates, badges.

Scope `progress:read` (D1). The `school` section of the summary needs `marks:read`
as well; without it the section says which scope is missing.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.not_wired import NotWired
from app.interfaces.mcp.toolkit import ToolKit
from app.interfaces.mcp.untrusted import mark_untrusted
from app.shared.base_error import NotFoundError
from app.shared.contracts.mcp_learning_record import McpLearningRecordTools

from pydantic import Field

SCOPE = "progress:read"
MARKS_SCOPE = "marks:read"

Section = Literal["courses", "school"]


def learning(kit: ToolKit) -> McpLearningRecordTools:
    """The learning-record backend; refuses as internal when the process has none."""
    backend = kit.deps.learning_tools
    if backend is None:
        return NotWired("mcp_learning_tools")  # type: ignore[return-value]
    return backend


def register(kit: ToolKit) -> None:  # noqa: C901 - one closure per tool
    """Register `get_learning_record`, `get_my_course_progress` and the lists."""

    @kit.tool(SCOPE)
    async def get_learning_record(
        sections: Annotated[
            list[Section] | None,
            Field(description="Sections to include; all when omitted."),
        ] = None,
    ) -> dict[str, Any]:
        """Summarize the student's learning: courses and, with marks:read, school.

        Per enrolled course: progress, score and passing percentages, required steps
        left, the certificate (tier, date, verify link) and badges earned. `school`
        is the platform GPA with per-subject semester marks, or
        `{"withheld": "marks:read"}` when the token lacks that scope.
        """
        actor = current_actor()
        wanted = set(sections or ("courses", "school"))
        result: dict[str, Any] = {}
        if "courses" in wanted:
            courses = await learning(kit).courses(actor)
            result["courses"] = courses
            result["certificates_count"] = sum(
                1 for c in courses if c["certificate"] is not None
            )
        if "school" in wanted:
            if await kit.guard.has_scope(actor, MARKS_SCOPE):
                try:
                    result["school"] = await kit.deps.academic_tools.gpa(
                        actor.user_id, None
                    )
                except NotFoundError:
                    result["school"] = None
            else:
                result["school"] = {"withheld": MARKS_SCOPE}
        return mark_untrusted(result, "courses[].title")

    @kit.tool(SCOPE)
    async def get_my_course_progress(
        course_id: Annotated[
            UUID, Field(description="Course id from get_learning_record.")
        ],
    ) -> dict[str, Any]:
        """Show the mastery map of an enrolled course: sections, steps and points.

        Each section has `mastery_pct` and `unlocked`; each test step its
        `max_points`, the student's `best_points` and `completed`.
        """
        actor = current_actor()
        view = await learning(kit).course_progress(actor, course_id)
        return mark_untrusted(
            view, "title", "sections[].title", "sections[].steps[].title"
        )

    @kit.tool(SCOPE)
    async def list_my_certificates() -> dict[str, Any]:
        """List the student's course certificates and school certificate entries.

        Course: tier, issue date and the public verify link. School: type, title
        and date. No files.
        """
        actor = current_actor()
        found = await learning(kit).my_certificates(actor)
        return mark_untrusted(found, "course[].title", "school[].title")

    @kit.tool(SCOPE)
    async def list_my_badges() -> dict[str, Any]:
        """List the badges the student earned in courses and those still locked."""
        actor = current_actor()
        found = await learning(kit).my_badges(actor)
        return mark_untrusted(
            found,
            "earned[].title",
            "earned[].course_title",
            "locked[].title",
            "locked[].course_title",
        )
