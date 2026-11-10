"""LMS Course tool `generate_course_draft`."""

from typing import Annotated, Any
from uuid import UUID

from app.interfaces.mcp.call_log import LogSpec
from app.interfaces.mcp.guard import current_actor
from app.interfaces.mcp.lms.course_scope import ensure_course
from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import (
    CoursePlanInput,
    build_text_block,
    step_brief,
)
from app.shared.lms_scopes import MODULES_WRITE

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

SCOPE = MODULES_WRITE


def register(kit: ToolKit) -> None:
    """Register `generate_course_draft`."""

    @kit.tool(
        SCOPE,
        read_only=False,
        log=LogSpec(keep=("sections", "steps_per_section", "course_id", "apply")),
    )
    async def generate_course_draft(
        topic: Annotated[str, Field(min_length=3, max_length=300)],
        language: Annotated[str, Field(pattern=r"^(uz|ru|en)$")] = "en",
        audience: Annotated[str, Field(max_length=300)] = "",
        sections: Annotated[int, Field(ge=1, le=12)] = 4,
        steps_per_section: Annotated[int, Field(ge=1, le=8)] = 3,
        course_id: Annotated[
            UUID | None,
            Field(description="With apply=true: course that receives the outline."),
        ] = None,
        apply: Annotated[
            bool, Field(description="True creates sections and steps in course_id.")
        ] = False,
    ) -> dict[str, Any]:
        """Draft a course outline with the platform AI; optionally build it.

        Returns the plan. With apply=true and course_id the sections and steps are
        created in the draft (each step gets a text block with its brief); then fill
        them with generate_lesson or the add_* tools.
        """
        actor = current_actor()
        ai = kit.deps.lms_ai
        if ai is None:
            raise ToolError(
                "AI drafting is not available on this server; write the outline "
                "yourself and use build_course."
            )
        if apply:
            if course_id is None:
                raise ToolError("apply=true needs course_id; create_course first.")
            await ensure_course(kit, actor, course_id)
        plan = await ai.course_plan(
            actor,
            topic=topic,
            audience=audience,
            language=language,
            sections=sections,
            steps_per_section=steps_per_section,
        )
        if apply and course_id is not None:
            parsed = CoursePlanInput.model_validate(plan)
            outline = [
                {
                    "title": s.title,
                    "steps": [
                        {
                            "title": st.title,
                            "blocks": [build_text_block(step_brief(st, language))],
                        }
                        for st in s.steps
                    ],
                }
                for s in parsed.sections
            ]
            built = await kit.deps.lms_ops.build_course(actor, course_id, outline)
            return {"plan": plan, "applied": built}
        return {"plan": plan}
