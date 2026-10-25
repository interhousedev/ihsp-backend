"""Author tool (write): add one step at the end of a section."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    draft_commands_of,
    lms_call,
    scope_of,
    workspace_commands_of,
)
from app.modules.ai.application.tools.lms_writes import course_section, same_title
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField

from pydantic import Field


class CreateStepArgs(ToolArgs):
    """The section, the title and an optional brief of the new step."""

    section_id: str = Field(
        min_length=1, max_length=64, description="Section id from the course outline."
    )
    title: str = Field(
        min_length=1, max_length=200, description="Step title, without numbering."
    )
    brief: str | None = Field(
        default=None,
        max_length=2000,
        description="Markdown goals and plan; becomes the step's first text block.",
    )


class CreateStep(AuthorWriteTool[CreateStepArgs]):
    """Adds an empty step (or one with its brief) after the section's last step."""

    name = "create_step"
    description = (
        "Add ONE step at the end of a section of this course (needs approval). "
        "Give `brief` (Markdown learning goals and plan) to start the step with it "
        "as a text block; fill it afterwards with replace_step_content or the add_* "
        "tools. A step with the same title in that section is not created twice. "
        "For several steps use apply_outline. Result: step_id, section_id, title. "
        'Example: create_step {"section_id": "s-3f2a", "title": "Chain rule"}'
    )
    args_model = CreateStepArgs

    async def validate(self, args: CreateStepArgs, ctx: ToolContext) -> None:
        """The section must be in the course and must not have this step yet."""
        _, section = await course_section(self.bindings, ctx, args.section_id)
        for step in section.steps:
            if same_title(step.title, args.title):
                raise ToolFailedError(
                    support_details="the step already exists (step_id "
                    f"{step.step_id}); do not create it again"
                )

    async def preview(self, args: CreateStepArgs, ctx: ToolContext) -> PreviewData:
        """Show the step, its section and the brief's first lines."""
        _, section = await course_section(self.bindings, ctx, args.section_id)
        fields = []
        if args.brief:
            fields.append(PreviewField(label_key="ai-field-brief", value=args.brief))
        return PreviewData(
            title_key="ai-preview-create-step",
            title_params={"title": args.title, "section": section.title},
            fields=fields,
        )

    async def run(self, args: CreateStepArgs, ctx: ToolContext) -> dict[str, Any]:
        """Create the step through the outline (marked as AI) when titles allow."""
        scope = scope_of(ctx)
        brief, section = await course_section(self.bindings, ctx, args.section_id)
        twins = [s for s in brief.sections if same_title(s.title, section.title)]
        if len(twins) > 1:  # the outline matches sections by title: be exact here
            made = await lms_call(
                draft_commands_of(self.bindings).create_step(
                    ctx.actor,
                    scope.course_id,
                    args.section_id,
                    args.title,
                    via_mcp=False,
                )
            )
            return {**made, "brief_added": False}
        step: dict[str, Any] = {"title": args.title}
        if args.brief:
            step["brief"] = args.brief
        done = await lms_call(
            workspace_commands_of(self.bindings).apply_outline(
                ctx.actor,
                scope.course_id,
                [{"title": section.title, "steps": [step]}],
                add_briefs=bool(args.brief),
                via_ai=True,
            )
        )
        created = list(done.get("created_steps") or [])
        if not created:
            raise ToolFailedError(support_details="the step already exists")
        return {**created[0], "brief_added": bool(args.brief)}
