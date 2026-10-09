"""Author tool (write): write a ready Studio output into the course draft."""

from typing import Any, Literal
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    course_step,
    lms_call,
    notebook_commands_of,
    notebook_queries_of,
    scope_of,
    step_title,
    workspace_commands_of,
)
from app.modules.ai.application.tools.lms_shapes import block_line, outline_lines
from app.modules.ai.application.tools.lms_writes import course_section
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField

from pydantic import Field

APPLICABLE = ("course_plan", "lesson_draft", "quiz", "flashcards")
NEEDS_STEP = ("quiz", "flashcards")
NOT_READY = (
    "the output is not ready or not found: check its status with "
    "list_workspace_outputs"
)


class ApplyStudioOutputArgs(ToolArgs):
    """A ready output and where in the course it goes."""

    artifact_id: UUID = Field(description="Output id from list_workspace_outputs.")
    target_step_id: UUID | None = Field(
        default=None,
        description="lesson_draft: the step to fill; quiz, flashcards: the step to "
        "append to.",
    )
    target_section_id: str | None = Field(
        default=None,
        max_length=64,
        description="lesson_draft without a step: the section of the new step.",
    )
    mode: Literal["replace", "append"] | None = Field(
        default=None,
        description="lesson_draft into a step: replace (default) or append.",
    )


class ApplyStudioOutput(AuthorWriteTool[ApplyStudioOutputArgs]):
    """The "Apply to the course" of the workspace, after the teacher approves."""

    name = "apply_studio_output"
    description = (
        "Write a READY Studio output of this course's workspace into the course "
        "draft (needs approval). course_plan: creates the missing sections and "
        "steps (nothing is renamed or removed). lesson_draft: fills "
        "target_step_id (mode replace, the default, or append) or creates a new "
        "step in target_section_id. quiz, flashcards: appended to target_step_id "
        "as a test or flash cards block. Result: created_sections, created_steps, "
        "step_id, lock_version, draft_seq. Example: apply_studio_output "
        '{"artifact_id": "0192f0c4-...-c3d4", "target_step_id": "0192f0c4-...-7d1e"}'
    )
    args_model = ApplyStudioOutputArgs

    async def _output(
        self, args: ApplyStudioOutputArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        scope = scope_of(ctx)
        found = await lms_call(
            notebook_queries_of(self.bindings).get_artifact_content(
                ctx.actor.user_id, scope.notebook_id, args.artifact_id
            )
        )
        if found is None:
            raise ToolFailedError(support_details=NOT_READY)
        kind = str(found.get("kind"))
        if kind not in APPLICABLE:
            raise ToolFailedError(
                support_details=f"a {kind} output cannot be written into a course"
            )
        if kind in NEEDS_STEP and args.target_step_id is None:
            raise ToolFailedError(
                support_details=f"a {kind} output needs target_step_id"
            )
        if (
            kind == "lesson_draft"
            and args.target_step_id is None
            and args.target_section_id is None
        ):
            raise ToolFailedError(
                support_details="a lesson_draft needs target_step_id or "
                "target_section_id"
            )
        return found

    async def validate(self, args: ApplyStudioOutputArgs, ctx: ToolContext) -> None:
        """The output must be ready and the targets must be in the course."""
        notebook_commands_of(self.bindings)
        await self._output(args, ctx)
        if args.target_step_id is not None:
            await course_step(self.bindings, ctx, args.target_step_id)
        if args.target_section_id is not None:
            await course_section(self.bindings, ctx, args.target_section_id)

    async def preview(
        self, args: ApplyStudioOutputArgs, ctx: ToolContext
    ) -> PreviewData:
        """Show the output, its target and what it brings."""
        found = await self._output(args, ctx)
        content = found.get("content") or {}
        fields: list[PreviewField] = []
        if args.target_step_id is not None:
            draft = await course_step(self.bindings, ctx, args.target_step_id)
            fields.append(
                PreviewField(label_key="ai-field-step", value=step_title(draft))
            )
        if args.target_section_id is not None:
            _, section = await course_section(
                self.bindings, ctx, args.target_section_id
            )
            fields.append(
                PreviewField(label_key="ai-field-section", value=section.title)
            )
        if args.mode is not None:
            fields.append(PreviewField(label_key="ai-field-mode", value=args.mode))
        return PreviewData(
            title_key="ai-preview-apply-studio-output",
            title_params={"title": str(found.get("title") or "")},
            fields=fields,
            items=await self._items(str(found.get("kind")), content, ctx),
        )

    async def _items(
        self, kind: str, content: dict[str, Any], ctx: ToolContext
    ) -> list[str]:
        if kind == "course_plan":
            sections = [
                {
                    "title": str(s.get("title", "")),
                    "steps": [
                        {"title": str(t.get("title", ""))} for t in s.get("steps") or []
                    ],
                }
                for s in content.get("sections") or []
            ]
            plan = await lms_call(
                workspace_commands_of(self.bindings).apply_outline(
                    ctx.actor,
                    scope_of(ctx).course_id,
                    sections,
                    dry_run=True,
                    via_ai=True,
                )
            )
            return outline_lines(self.i18n, ctx.locale, list(plan.get("plan") or []))
        if kind == "lesson_draft":
            return [
                block_line(self.i18n, ctx.locale, b)
                for b in content.get("blocks") or []
                if isinstance(b, dict)
            ]
        key = "ai-item-test" if kind == "quiz" else "ai-item-cards"
        items = content.get("questions") if kind == "quiz" else content.get("cards")
        return [self.i18n.t(ctx.locale, key, count=len(items or []))]

    async def run(
        self, args: ApplyStudioOutputArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Apply the output through the notebooks module (it checks ``edit``)."""
        scope = scope_of(ctx)
        return await lms_call(
            notebook_commands_of(self.bindings).apply_artifact(
                ctx.actor,
                scope.notebook_id,
                args.artifact_id,
                target_step_id=args.target_step_id,
                target_section_id=args.target_section_id,
                mode=args.mode,
            )
        )
