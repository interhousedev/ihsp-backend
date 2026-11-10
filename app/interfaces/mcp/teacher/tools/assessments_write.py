"""Teacher tools `create_assessment` and `update_assessment`."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.constants import WRITE_LIMIT
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.toolkit import ToolKit

from pydantic import Field

SCOPE = "assessments:write"

_TITLE_MAX = 200


def register(kit: ToolKit) -> None:
    """Register the assessment writing tools."""

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=False,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("subject_id", "kind", "day")),
    )
    async def create_assessment(
        subject_id: Annotated[
            UUID, Field(description="A subject the teacher teaches.")
        ],
        group_ids: Annotated[
            list[UUID],
            Field(min_length=1, max_length=20, description="Whole groups to test."),
        ],
        kind: Annotated[
            Literal["midterm", "final", "other"],
            Field(description="midterm: ПК, final: ИК, other: a test or quiz."),
        ],
        day: Annotated[date, Field(description="The date, YYYY-MM-DD.")],
        title: Annotated[str, Field(max_length=_TITLE_MAX)] = "",
        room: Annotated[str | None, Field(max_length=100)] = None,
        note: Annotated[str | None, Field(max_length=1000)] = None,
    ) -> dict[str, Any]:
        """Plan a control for whole groups; the teacher must teach them the subject."""
        return await kit.deps.teacher_tools.create_assessment(
            current_actor(),
            subject_id=subject_id,
            group_ids=group_ids,
            kind=kind,
            day=day,
            title=title,
            room=room,
            note=note,
        )

    @kit.tool(
        SCOPE,
        read_only=False,
        idempotent=True,
        limit=WRITE_LIMIT,
        log=LogSpec(keep=("assessment_id", "day", "status")),
    )
    async def update_assessment(
        assessment_id: Annotated[UUID, Field(description="A control of the teacher.")],
        title: Annotated[str | None, Field(max_length=_TITLE_MAX)] = None,
        day: Annotated[date | None, Field(description="New date, YYYY-MM-DD.")] = None,
        room: Annotated[str | None, Field(max_length=100)] = None,
        note: Annotated[str | None, Field(max_length=1000)] = None,
        status: Annotated[
            Literal["planned", "cancelled"] | None,
            Field(description="cancelled: drop the control; planned: confirm it."),
        ] = None,
    ) -> dict[str, Any]:
        """Change the sent fields of a control; omitted fields stay as they are."""
        changes: dict[str, Any] = {
            name: value
            for name, value in (
                ("title", title),
                ("date", day),
                ("room", room),
                ("note", note),
                ("status", status),
            )
            if value is not None
        }
        if not changes:
            raise McpInvalidInputError(params={"reason": "nothing to change"})
        return await kit.deps.teacher_tools.update_assessment(
            current_actor(), assessment_id, changes
        )
