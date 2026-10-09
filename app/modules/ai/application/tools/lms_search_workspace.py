"""Author tool: search the passages of the course workspace's sources."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.lms_base import AuthorReadTool
from app.modules.ai.application.tools.lms_common import (
    lms_call,
    notebook_queries_of,
    scope_of,
)
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field


class SearchWorkspaceArgs(ToolArgs):
    """A search phrase and how many passages to return."""

    query: str = Field(
        min_length=1,
        max_length=200,
        description="Key terms to look for, in the language of the sources.",
    )
    limit: int = Field(default=8, ge=1, le=20, description="Passages to return.")


class SearchWorkspace(AuthorReadTool[SearchWorkspaceArgs]):
    """Passages of the workspace sources, best match first."""

    name = "search_workspace"
    description = (
        "Search the sources of this course's workspace. Call it BEFORE writing "
        "facts, definitions, formulas or dates, and prefer what it finds. Returns "
        "passages (source_id, source_title, seq, page, text up to 600 characters), "
        "best match first; words are matched, not meaning, so use the key terms "
        "(try a synonym or the other language if nothing is found). An empty result "
        "means the sources do not cover it: say so before using general knowledge. "
        'Example: search_workspace {"query": "derivative definition", "limit": 5}'
    )
    args_model = SearchWorkspaceArgs

    async def run(self, args: SearchWorkspaceArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the passages of the scope's workspace."""
        scope = scope_of(ctx)
        rows = await lms_call(
            notebook_queries_of(self.bindings).search(
                ctx.actor.user_id, scope.notebook_id, args.query, args.limit
            )
        )
        return capped(rows)
