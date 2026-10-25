"""Author tool: read one page of a source of the course workspace."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.lms_base import AuthorReadTool
from app.modules.ai.application.tools.lms_common import (
    lms_call,
    notebook_queries_of,
    scope_of,
)
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field


class ReadWorkspaceSourceArgs(ToolArgs):
    """A source of the workspace and a page number."""

    source_id: UUID = Field(
        description="Source id from list_workspace_sources or search_workspace."
    )
    page: int = Field(
        default=1, ge=1, le=1000, description="Page to read, from 1 (8 KB each)."
    )


class ReadWorkspaceSource(AuthorReadTool[ReadWorkspaceSourceArgs]):
    """One 8 KB page of a workspace source's text."""

    name = "read_workspace_source"
    description = (
        "Read one page (up to 8 KB of text) of a source of this course's workspace. "
        "Use it when a search_workspace passage is too short to write from, or to "
        "follow a source in order; the result has page, pages (total) and text. "
        "Do not read whole long sources page by page without a reason; search "
        "first. Example: read_workspace_source "
        '{"source_id": "0192f0c4-...-a1b2", "page": 2}'
    )
    args_model = ReadWorkspaceSourceArgs

    async def run(
        self, args: ReadWorkspaceSourceArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the page; a source of another notebook fails the call."""
        scope = scope_of(ctx)
        return await lms_call(
            notebook_queries_of(self.bindings).read_source_page(
                ctx.actor.user_id, scope.notebook_id, args.source_id, args.page
            )
        )
