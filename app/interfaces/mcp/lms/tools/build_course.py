"""LMS Course tool `build_course`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.block_args import block_dict
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import BlockInput
from app.shared.lms_scopes import MODULES_WRITE

from pydantic import BaseModel, Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `build_course`."""

    class StepSpec(BaseModel):
        """One step to create."""

        title: str = Field(min_length=1, max_length=200)
        blocks: list[BlockInput] | None = Field(
            default=None, max_length=40, description="Blocks in reading order."
        )

    class SectionSpec(BaseModel):
        """One section to create with its steps."""

        title: str = Field(min_length=1, max_length=200)
        steps: list[StepSpec] = Field(min_length=1, max_length=50)

    @kit.tool(SCOPE, read_only=False, log=LogSpec(keep=("course_id",)))
    async def build_course(
        course_id: Annotated[UUID, Field(description="Course id from list_courses.")],
        sections: Annotated[
            list[SectionSpec],
            Field(min_length=1, max_length=30, description="Sections to append."),
        ],
    ) -> dict[str, Any]:
        """Create sections, steps and their blocks of a course in one call.

        Appends to the draft; nothing is published. Example: sections=[{"title":
        "Week 1", "steps": [{"title": "Intro", "blocks": [{"type": "text",
        "markdown": "Hello"}]}]}]. Check the result with get_course.
        """
        actor = current_actor()
        await ensure_course(kit, actor, course_id)
        plan = [
            {
                "title": section.title,
                "steps": [
                    {
                        "title": step.title,
                        "blocks": [block_dict(b) for b in step.blocks or []],
                    }
                    for step in section.steps
                ],
            }
            for section in sections
        ]
        return await kit.deps.lms_ops.build_course(actor, course_id, plan)
