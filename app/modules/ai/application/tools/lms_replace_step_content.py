"""Author tool (write): rewrite a whole step (title and blocks) in one call."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    CONFLICT,
    block_rule,
    course_step,
    draft_blocks,
    lms_call,
    step_title,
    workspace_commands_of,
)
from app.modules.ai.application.tools.lms_shapes import block_line, keep_line
from app.modules.ai.domain.errors import ToolArgumentsError, ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData, PreviewField
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    FlashcardsBlockInput,
    TestBlockInput,
    TextBlockInput,
    build_block,
)

from pydantic import BaseModel, ConfigDict, Field


class KeepBlockInput(BaseModel):
    """An existing block that stays as it is (by its number in get_step_draft)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["keep"] = "keep"
    block: int = Field(ge=1, le=40, description="Number of the existing block.")


StepBlockArg = Annotated[
    TextBlockInput | TestBlockInput | FlashcardsBlockInput | KeepBlockInput,
    Field(discriminator="type"),
]


class ReplaceStepContentArgs(ToolArgs):
    """The new content of a step and the lock_version it was read with."""

    step_id: UUID = Field(description="Step id from the course outline.")
    lock_version: int = Field(
        ge=0, description="lock_version from your last get_step_draft of this step."
    )
    title: str = Field(
        min_length=1, max_length=200, description="Step title, without numbering."
    )
    blocks: list[StepBlockArg] = Field(
        min_length=1,
        max_length=40,
        description="All blocks in reading order: new ones and kept ones.",
    )


class ReplaceStepContent(AuthorWriteTool[ReplaceStepContentArgs]):
    """Replaces the step's draft; kept blocks are copied from the current draft."""

    name = "replace_step_content"
    description = (
        "Rewrite a whole step of this course in ONE call (needs approval): its "
        "title and all its blocks in order. Call get_step_draft first and pass its "
        "lock_version. Each block is new (type text, test or flashcards, as in "
        'add_*) or an existing block kept unchanged: {"type": "keep", "block": N} '
        "(N from get_step_draft; never copy a kept block's content). Existing "
        "blocks you leave out are REMOVED: say so in your proposal. Use it to write "
        "a lesson into an empty step or to restructure a step. On draft-conflict "
        "re-read the step once and retry. Result: step_id, blocks_total, "
        'lock_version. Example: replace_step_content {"step_id": '
        '"0192f0c4-...-7d1e", "lock_version": 3, "title": "Limits", "blocks": '
        '[{"type": "text", "markdown": "### Idea\\n..."}, {"type": "keep", '
        '"block": 2}]}'
    )
    args_model = ReplaceStepContentArgs

    async def _content(
        self, args: ReplaceStepContentArgs, ctx: ToolContext
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return the step's current draft and the new content built from the args."""
        draft = await course_step(self.bindings, ctx, args.step_id)
        current = int(draft.get("lock_version") or 0)
        if current != args.lock_version:
            raise ToolFailedError(
                support_details=CONFLICT.format(
                    current=f" (current lock_version {current})"
                )
            )
        existing = draft_blocks(draft)
        blocks: list[dict[str, Any]] = []
        kept: set[int] = set()
        for n, block in enumerate(args.blocks, start=1):
            if isinstance(block, KeepBlockInput):
                blocks.append(_kept(existing, block.block, n, kept))
                continue
            try:
                blocks.append(build_block(block))
            except BlockInputError as exc:
                raise block_rule(exc, f"blocks.{n}") from exc
        return draft, {"title": args.title, "blocks": blocks}

    async def validate(self, args: ReplaceStepContentArgs, ctx: ToolContext) -> None:
        """The step must be ours, unchanged since it was read, the blocks valid."""
        await self._content(args, ctx)

    async def preview(
        self, args: ReplaceStepContentArgs, ctx: ToolContext
    ) -> PreviewData:
        """List every block of the new step: new, kept, and the removed ones."""
        draft, content = await self._content(args, ctx)
        existing = draft_blocks(draft)
        kept = {b.block for b in args.blocks if isinstance(b, KeepBlockInput)}
        items: list[str] = []
        for block, arg in zip(content["blocks"], args.blocks, strict=True):
            if isinstance(arg, KeepBlockInput):
                items.append(keep_line(self.i18n, ctx.locale, arg.block, block))
            else:
                items.append(block_line(self.i18n, ctx.locale, block))
        items.extend(
            self.i18n.t(
                ctx.locale,
                "ai-item-drop",
                n=n,
                block=block_line(self.i18n, ctx.locale, block),
            )
            for n, block in enumerate(existing, start=1)
            if n not in kept
        )
        fields = []
        old_title = step_title(draft)
        if old_title != args.title:
            fields.append(
                PreviewField(label_key="ai-field-new-title", value=args.title)
            )
        return PreviewData(
            title_key="ai-preview-replace-step-content",
            title_params={"step": old_title, "count": len(content["blocks"])},
            fields=fields,
            items=items,
        )

    async def run(
        self, args: ReplaceStepContentArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Save the new content with the lock_version (marked as changed by AI)."""
        _, content = await self._content(args, ctx)
        done = await lms_call(
            workspace_commands_of(self.bindings).replace_step(
                ctx.actor, args.step_id, content, args.lock_version, via_ai=True
            )
        )
        return {
            "step_id": str(args.step_id),
            "title": args.title,
            "blocks_total": len(content["blocks"]),
            "lock_version": done.get("lock_version"),
        }


def _kept(
    existing: list[dict[str, Any]], number: int, position: int, kept: set[int]
) -> dict[str, Any]:
    if number > len(existing):
        text = (
            f"blocks.{position}: the step has {len(existing)} blocks; block {number} "
            "does not exist"
        )
        raise ToolArgumentsError(params={"details": text}, support_details=text)
    if number in kept:
        text = f"blocks.{position}: block {number} is kept twice; keep it once"
        raise ToolArgumentsError(params={"details": text}, support_details=text)
    kept.add(number)
    return existing[number - 1]
