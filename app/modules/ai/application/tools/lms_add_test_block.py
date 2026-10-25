"""Author tool (write): append a test block with all its questions to a step."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    block_rule,
    course_step,
    step_title,
)
from app.modules.ai.application.tools.lms_shapes import question_lines
from app.modules.ai.application.tools.lms_writes import append_block
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    QuestionInput,
    QuizSettingsInput,
    build_test_block,
)

from pydantic import Field


class AddTestBlockArgs(ToolArgs):
    """The step, the questions and (rarely) the settings of the test."""

    step_id: UUID = Field(description="Step id from the course outline.")
    questions: list[QuestionInput] = Field(
        min_length=1, max_length=50, description="All questions of the test."
    )
    settings: QuizSettingsInput | None = Field(
        default=None, description="Omit for the defaults unless the teacher asks."
    )


def built_test(args: AddTestBlockArgs) -> dict[str, Any]:
    """Return the test block or raise the argument error the model can fix."""
    try:
        return build_test_block(args.settings, args.questions)
    except BlockInputError as exc:
        raise block_rule(exc, "questions") from exc


class AddTestBlock(AuthorWriteTool[AddTestBlockArgs]):
    """Adds one test block after the step's last block."""

    name = "add_test_block"
    description = (
        "Append ONE test block with ALL its questions to the end of a step's draft "
        "(needs approval). Question types: single (exactly one correct option), "
        "multiple (one or more correct), text (accepted_answers or regex), number "
        "(number and tolerance). Choice questions need 2 to 10 options with "
        "plausible distractors; add an explanation. Ask only what the step teaches. "
        "Leave out settings unless the teacher asked for attempts, time limits or "
        "shuffling. Result: step_id, block, blocks_total. Example: add_test_block "
        '{"step_id": "0192f0c4-...-7d1e", "questions": [{"type": "single", '
        '"prompt": "2 + 2 = ?", "options": [{"text": "4", "correct": true}, '
        '{"text": "5"}], "explanation": "2 + 2 is 4."}]}'
    )
    args_model = AddTestBlockArgs

    async def validate(self, args: AddTestBlockArgs, ctx: ToolContext) -> None:
        """Questions must follow the rules of their types; the step must be ours."""
        built_test(args)
        await course_step(self.bindings, ctx, args.step_id)

    async def preview(self, args: AddTestBlockArgs, ctx: ToolContext) -> PreviewData:
        """Show every question with its right answer."""
        draft = await course_step(self.bindings, ctx, args.step_id)
        block = built_test(args)
        return PreviewData(
            title_key="ai-preview-add-test-block",
            title_params={"step": step_title(draft), "count": len(args.questions)},
            items=question_lines(self.i18n, ctx.locale, block),
        )

    async def run(self, args: AddTestBlockArgs, ctx: ToolContext) -> dict[str, Any]:
        """Append the test (marked as changed by AI)."""
        return await append_block(self.bindings, ctx, args.step_id, built_test(args))
