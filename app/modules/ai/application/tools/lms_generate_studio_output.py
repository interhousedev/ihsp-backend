"""Author tool (write): start a Studio output in the course workspace."""

from typing import Any, Literal
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    course_step,
    lms_call,
    notebook_commands_of,
    scope_of,
    step_title,
)
from app.modules.ai.domain.errors import ToolArgumentsError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField

from pydantic import Field

StudioKind = Literal["course_plan", "lesson_draft", "quiz", "flashcards"]
OPTIONS_OF: dict[str, tuple[str, ...]] = {
    "course_plan": ("depth", "sections_hint", "language"),
    "lesson_draft": (
        "step_id",
        "topic",
        "include_test",
        "include_flashcards",
        "length",
        "language",
    ),
    "quiz": ("count", "difficulty", "language"),
    "flashcards": ("count", "difficulty", "language"),
}
OPTION_NAMES = sorted({name for names in OPTIONS_OF.values() for name in names})


class GenerateStudioOutputArgs(ToolArgs):
    """The kind of output and the options that belong to it."""

    kind: StudioKind = Field(description="What to generate from the sources.")
    prompt: str | None = Field(
        default=None, max_length=1000, description="What to focus on (optional)."
    )
    depth: Literal["overview", "detailed"] | None = Field(
        default=None, description="course_plan only."
    )
    sections_hint: int | None = Field(
        default=None, ge=1, le=30, description="course_plan only: about N sections."
    )
    step_id: UUID | None = Field(
        default=None, description="lesson_draft only: the existing step to draft."
    )
    topic: str | None = Field(
        default=None, max_length=200, description="lesson_draft only: a new topic."
    )
    include_test: bool | None = Field(default=None, description="lesson_draft only.")
    include_flashcards: bool | None = Field(
        default=None, description="lesson_draft only."
    )
    length: Literal["short", "standard", "long"] | None = Field(
        default=None, description="lesson_draft only."
    )
    count: Literal["fewer", "standard", "more"] | None = Field(
        default=None, description="quiz and flashcards only."
    )
    difficulty: Literal["easy", "medium", "hard"] | None = Field(
        default=None, description="quiz and flashcards only."
    )
    language: Literal["uz", "ru", "en"] | None = Field(
        default=None, description="Output language; omit for the course language."
    )


def studio_options(args: GenerateStudioOutputArgs) -> dict[str, Any]:
    """Return the options of the kind; an option of another kind is an error."""
    given = {
        name: getattr(args, name)
        for name in OPTION_NAMES
        if getattr(args, name) is not None
    }
    wrong = sorted(set(given) - set(OPTIONS_OF[args.kind]))
    if wrong:
        text = f"{', '.join(wrong)}: not an option of {args.kind}"
        raise ToolArgumentsError(params={"details": text}, support_details=text)
    return {k: str(v) if isinstance(v, UUID) else v for k, v in given.items()}


class GenerateStudioOutput(AuthorWriteTool[GenerateStudioOutputArgs]):
    """Queues a course plan, lesson draft, quiz or flash cards in the workspace."""

    name = "generate_studio_output"
    description = (
        "Start a Studio output in this course's workspace (needs approval; it is a "
        "slow background job and uses one of the teacher's daily outputs). Use it "
        "ONLY when the teacher asks for a Studio output; otherwise write the "
        "content yourself with the other tools. kind: course_plan {depth?, "
        "sections_hint?}, lesson_draft {step_id? (an existing step) or topic?, "
        "include_test?, include_flashcards?, length?}, quiz or flashcards {count?, "
        "difficulty?}; any kind {language?, prompt?}. Result: id, kind, status. "
        "Check list_workspace_outputs later; write a ready output into the course "
        "with apply_studio_output. Example: generate_studio_output "
        '{"kind": "course_plan", "depth": "detailed", "sections_hint": 5}'
    )
    args_model = GenerateStudioOutputArgs

    async def validate(self, args: GenerateStudioOutputArgs, ctx: ToolContext) -> None:
        """Options must fit the kind; a lesson step must belong to the course."""
        notebook_commands_of(self.bindings)
        studio_options(args)
        if args.step_id is not None:
            await course_step(self.bindings, ctx, args.step_id)

    async def preview(
        self, args: GenerateStudioOutputArgs, ctx: ToolContext
    ) -> PreviewData:
        """Show the kind, its options and the focus."""
        options = studio_options(args)
        fields: list[PreviewField] = []
        if args.step_id is not None:
            draft = await course_step(self.bindings, ctx, args.step_id)
            fields.append(
                PreviewField(label_key="ai-field-step", value=step_title(draft))
            )
        shown = ", ".join(
            f"{k}: {v}" for k, v in sorted(options.items()) if k != "step_id"
        )
        if shown:
            fields.append(PreviewField(label_key="ai-field-options", value=shown))
        if args.prompt:
            fields.append(PreviewField(label_key="ai-field-prompt", value=args.prompt))
        return PreviewData(
            title_key="ai-preview-generate-" + args.kind.replace("_", "-"),
            fields=fields,
        )

    async def run(
        self, args: GenerateStudioOutputArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Queue the output in the scope's workspace."""
        scope = scope_of(ctx)
        created = await lms_call(
            notebook_commands_of(self.bindings).request_artifact(
                ctx.actor,
                scope.notebook_id,
                args.kind,
                studio_options(args),
                args.prompt,
            )
        )
        return {
            **created,
            "note": "generating in the background; check list_workspace_outputs",
        }
