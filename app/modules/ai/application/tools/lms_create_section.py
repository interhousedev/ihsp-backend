"""Author tool (write): add one section at the end of the draft outline."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorWriteTool
from app.modules.ai.application.tools.lms_common import (
    draft_commands_of,
    lms_call,
    scope_of,
)
from app.modules.ai.application.tools.lms_writes import course_brief, same_title
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData

from pydantic import Field


class CreateSectionArgs(ToolArgs):
    """The title of the new section."""

    title: str = Field(
        min_length=1, max_length=200, description="Section title, without numbering."
    )


class CreateSection(AuthorWriteTool[CreateSectionArgs]):
    """Adds an empty section after the last one."""

    name = "create_section"
    description = (
        "Add ONE empty section at the end of the course outline (needs approval). "
        "For several sections or sections with steps use apply_outline instead. "
        "Check the outline first so you do not create a duplicate. Result: "
        "section_id, title, draft_seq; then add steps with create_step. "
        'Example: create_section {"title": "Integrals"}'
    )
    args_model = CreateSectionArgs

    async def validate(self, args: CreateSectionArgs, ctx: ToolContext) -> None:
        """A section with the same title must not exist yet."""
        brief = await course_brief(self.bindings, ctx)
        for section in brief.sections:
            if same_title(section.title, args.title):
                raise ToolFailedError(
                    support_details="the section already exists (section_id "
                    f"{section.section_id}); do not create it again"
                )

    async def preview(self, args: CreateSectionArgs, ctx: ToolContext) -> PreviewData:
        """Show the new section's title."""
        return PreviewData(
            title_key="ai-preview-create-section", title_params={"title": args.title}
        )

    async def run(self, args: CreateSectionArgs, ctx: ToolContext) -> dict[str, Any]:
        """Add the section to the scope's course."""
        scope = scope_of(ctx)
        made = await lms_call(
            draft_commands_of(self.bindings).create_section(
                ctx.actor, scope.course_id, args.title, via_mcp=False
            )
        )
        return {
            "section_id": made.get("id"),
            "title": made.get("title", args.title),
            "draft_seq": made.get("draft_seq"),
        }
