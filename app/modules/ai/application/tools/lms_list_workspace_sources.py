"""Author tool: the sources of the course workspace."""

from typing import Any

from app.modules.ai.application.tools.base import ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.lms_base import AuthorReadTool
from app.modules.ai.application.tools.lms_common import (
    lms_call,
    notebook_queries_of,
    scope_of,
)
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs


class ListWorkspaceSourcesArgs(ToolArgs):
    """No arguments: the workspace is the chat's course workspace."""


class ListWorkspaceSources(AuthorReadTool[ListWorkspaceSourcesArgs]):
    """Files, texts, links, notes and course steps added to the workspace."""

    name = "list_workspace_sources"
    description = (
        "List the sources of this course's workspace: source_id, title, kind (file, "
        "text, url, note, lms_step, ...), status and words. Use it to see what "
        "material the teacher provided or to get a source_id for "
        "read_workspace_source. To find facts, use search_workspace instead. "
        "Example: list_workspace_sources {}"
    )
    args_model = ListWorkspaceSourcesArgs

    async def run(
        self, args: ListWorkspaceSourcesArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the workspace's sources."""
        scope = scope_of(ctx)
        found = await lms_call(
            notebook_queries_of(self.bindings).get_notebook(
                ctx.actor.user_id, scope.notebook_id
            )
        )
        if found is None:
            raise ToolFailedError(support_details="the course workspace is not found")
        return capped(
            [
                {
                    "source_id": s.get("id"),
                    "title": s.get("title"),
                    "kind": s.get("kind"),
                    "status": s.get("status"),
                    "words": s.get("words"),
                }
                for s in found.get("sources", [])
            ]
        )
