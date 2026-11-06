"""Students tool `get_marks`: marks by subject, for dates or exact semesters (A5)."""

from collections.abc import Iterable
from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.params import DateFromParam, DateToParam
from app.interfaces.mcp.ranges import check_range
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.academic import MarkRef

from pydantic import Field

SCOPE = "marks:read"
MAX_MARK_RANGE_DAYS = 366
MAX_SEMESTERS = 12


def by_subject(marks: Iterable[MarkRef]) -> list[dict[str, Any]]:
    """Group marks by subject; a subject without a mark has no entry at all."""
    subjects: dict[UUID, dict[str, Any]] = {}
    for mark in marks:
        entry = subjects.setdefault(
            mark.subject_id,
            {
                "subject_id": mark.subject_id,
                "subject_name": mark.subject_name,
                "marks": [],
            },
        )
        entry["marks"].append(
            {
                "semester": mark.semester,
                "type": mark.type,
                "value": mark.value,
                "date": mark.date,
                "lesson_id": mark.lesson_id,
            }
        )
    return sorted(subjects.values(), key=lambda s: s["subject_name"].casefold())


def register(kit: ToolKit) -> None:
    """Register `get_marks`."""

    @kit.tool(SCOPE, log=LogSpec(keep=("subject_id", "date_from", "date_to")))
    async def get_marks(
        subject_id: Annotated[
            UUID | None, Field(description="Only marks of this subject.")
        ] = None,
        date_from: DateFromParam = None,
        date_to: DateToParam = None,
        semesters: Annotated[
            list[Annotated[int, Field(ge=1, le=12)]] | None,
            Field(
                max_length=MAX_SEMESTERS,
                description="Exact semester numbers; not together with dates.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """List the student's own marks (lesson, midterm and final), by subject.

        Choose a date period (at most 366 days) or exact semesters, not both. Only
        real marks are listed: lessons and subjects without a mark are left out. With
        semesters the answer has one entry per semester asked, empty when it has none.
        """
        actor = current_actor()
        if semesters is not None and (date_from or date_to):
            raise McpInvalidInputError(
                params={"reason": "semesters cannot be combined with dates"}
            )
        check_range(date_from, date_to, max_days=MAX_MARK_RANGE_DAYS)
        marks = await kit.deps.marks.marks(
            actor.user_id, subject_id, date_from, date_to
        )
        if semesters is None:
            return {"subjects": by_subject(marks)}
        return {
            "semesters": [
                {
                    "semester": semester,
                    "subjects": by_subject(
                        mark for mark in marks if mark.semester == semester
                    ),
                }
                for semester in dict.fromkeys(semesters)
            ]
        }
