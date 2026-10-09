"""Author tool (write): create the missing sections and steps of an outline."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    lms_call,
    scope_of,
    workspace_commands_of,
)
from app.modules.ai.application.tools.lms_shapes import count_new, outline_lines
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField

from pydantic import BaseModel, ConfigDict, Field

NOTHING_NEW = (
    "nothing to create: every section and step of this outline already exists in "
    "the draft (titles are compared without case). Do not call apply_outline again."
)


class OutlineStepArg(BaseModel):
    """One step of the outline."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1, max_length=200, description="Step title, without numbering."
    )
    brief: str | None = Field(
        default=None,
        max_length=2000,
        description="Markdown: learning goals and plan of the step (used with "
        "add_briefs).",
    )


class OutlineSectionArg(BaseModel):
    """One section of the outline with its steps in order."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=1, max_length=200, description="Section title, without numbering."
    )
    steps: list[OutlineStepArg] = Field(default_factory=list, max_length=30)


class ApplyOutlineArgs(ToolArgs):
    """The whole outline: existing sections and steps are matched by title."""

    sections: list[OutlineSectionArg] = Field(min_length=1, max_length=30)
    add_briefs: bool = Field(
        default=False,
        description="True: each NEW step gets its brief as a first text block.",
    )


class ApplyOutline(AuthorWriteTool[ApplyOutlineArgs]):
    """Creates only what the draft outline is missing, in one approved call."""

    name = "apply_outline"
    description = (
        "Write an agreed outline into the course draft in ONE call (needs approval). "
        "Give the whole outline in order: sections with their steps. A section or "
        "step whose title already exists (case-insensitive) is reused; only missing "
        "ones are created at the end; nothing is renamed, moved or deleted. With "
        "add_briefs every NEW step gets its `brief` (Markdown goals and plan) as a "
        "first text block. Use it only after the teacher approved the outline. "
        "Limits: 30 sections, 30 steps each. Result: created_sections [{id, title}], "
        "created_steps [{step_id, section_id, title}], draft_seq. Example: "
        'apply_outline {"sections": [{"title": "Limits", "steps": [{"title": '
        '"What is a limit", "brief": "**Goals**\\n- explain a limit"}]}], '
        '"add_briefs": true}'
    )
    args_model = ApplyOutlineArgs

    async def _dry_run(
        self, args: ApplyOutlineArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        scope = scope_of(ctx)
        return await lms_call(
            workspace_commands_of(self.bindings).apply_outline(
                ctx.actor,
                scope.course_id,
                _sections(args),
                dry_run=True,
                add_briefs=args.add_briefs,
                via_ai=True,
            )
        )

    async def preview(self, args: ApplyOutlineArgs, ctx: ToolContext) -> PreviewData:
        """Show the outline tree marked new / exists (a dry run of the LMS)."""
        plan = await self._dry_run(args, ctx)
        rows = list(plan.get("plan") or []) or _as_rows(args)
        new_sections, new_steps = count_new(rows)
        if not new_sections and not new_steps:
            raise ToolFailedError(support_details=NOTHING_NEW)
        fields = []
        if args.add_briefs:
            fields.append(
                PreviewField(
                    label_key="ai-field-briefs",
                    value=self.i18n.t(ctx.locale, "ai-value-yes"),
                )
            )
        return PreviewData(
            title_key="ai-preview-apply-outline",
            title_params={"sections": new_sections, "steps": new_steps},
            fields=fields,
            items=outline_lines(self.i18n, ctx.locale, rows),
        )

    async def run(self, args: ApplyOutlineArgs, ctx: ToolContext) -> dict[str, Any]:
        """Create the missing sections and steps (marked as changed by AI)."""
        scope = scope_of(ctx)
        done = await lms_call(
            workspace_commands_of(self.bindings).apply_outline(
                ctx.actor,
                scope.course_id,
                _sections(args),
                add_briefs=args.add_briefs,
                via_ai=True,
            )
        )
        return {
            "created_sections": done.get("created_sections", []),
            "created_steps": done.get("created_steps", []),
            "existing_sections": done.get("existing_sections"),
            "existing_steps": done.get("existing_steps"),
            "draft_seq": done.get("draft_seq"),
        }


def _sections(args: ApplyOutlineArgs) -> list[dict[str, Any]]:
    return [
        {
            "title": section.title,
            "steps": [
                {"title": s.title, **({"brief": s.brief} if s.brief else {})}
                for s in section.steps
            ],
        }
        for section in args.sections
    ]


def _as_rows(args: ApplyOutlineArgs) -> list[dict[str, Any]]:
    """The outline as card rows when the LMS dry run has no `plan`."""
    return [
        {
            "title": section.title,
            "action": "new",
            "steps": [{"title": s.title, "action": "new"} for s in section.steps],
        }
        for section in args.sections
    ]
