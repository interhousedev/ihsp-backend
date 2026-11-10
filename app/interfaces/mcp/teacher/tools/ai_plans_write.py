"""Teacher AI tools `register_plan_template` and `generate_lesson_plan`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.constants import AI_LIMIT, WRITE_LIMIT
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.jsonable import to_jsonable
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.teacher_ai import (
    GenerateLessonPlanArgs,
    RegisterPlanTemplateArgs,
)

from pydantic import Field

SCOPE = "lesson-plans:write"


def register(kit: ToolKit) -> None:
    """Register the tools when the process has the AI backend."""
    ai = kit.deps.teacher_ai
    if ai is None:
        return

    @kit.tool(SCOPE, read_only=False, idempotent=False, limit=WRITE_LIMIT)
    async def register_plan_template(
        name: Annotated[str, Field(min_length=1, max_length=200)],
        template: Annotated[
            str | None,
            Field(max_length=20_000, description="The plan layout as text."),
        ] = None,
        description: Annotated[str | None, Field(max_length=1000)] = None,
        file_id: Annotated[
            UUID | None,
            Field(description="The teacher's uploaded .docx (use instead of text)."),
        ] = None,
    ) -> dict[str, Any]:
        """Store a lesson plan template: pass `template` text or a .docx `file_id`.

        To use a Word template, the teacher uploads the .docx in the files section
        first; then pass that file's id. Plans made from it come back as a .docx.
        """
        args = RegisterPlanTemplateArgs(name, template, description, file_id)
        result: dict[str, Any] = to_jsonable(
            await ai.register_plan_template(current_actor(), args)
        )
        return result

    @kit.tool(SCOPE, read_only=False, idempotent=False, limit=AI_LIMIT)
    async def generate_lesson_plan(
        topic: Annotated[str, Field(min_length=1, max_length=500)],
        lesson_id: Annotated[
            UUID | None, Field(description="One of the teacher's lessons.")
        ] = None,
        template_id: Annotated[
            UUID | None, Field(description="A template from `list_plan_templates`.")
        ] = None,
        duration_minutes: Annotated[int, Field(ge=10, le=240)] = 45,
        language: Annotated[str | None, Field(max_length=8)] = None,
        notes: Annotated[str | None, Field(max_length=2000)] = None,
    ) -> dict[str, Any]:
        """Generate a lesson plan (Markdown) and keep it for the teacher.

        A template made from a .docx also gives `docx_file_id`: the plan written
        into a copy of that document, kept as the teacher's file.
        """
        args = GenerateLessonPlanArgs(
            topic, lesson_id, template_id, duration_minutes, language, notes
        )
        result: dict[str, Any] = to_jsonable(
            await ai.generate_lesson_plan(current_actor(), args)
        )
        return result
