"""Tool: one notebook with its summary and sources."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.notebook_common import queries_of
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs


class GetNotebookArgs(ToolArgs):
    """A notebook."""

    notebook_id: UUID


class GetNotebook(ReadTool[GetNotebookArgs]):
    """Title, summary, key topics and the sources of a notebook."""

    name = "get_notebook"
    description = (
        "Open one of the student's notebooks: title, summary, key topics and its "
        "sources (id, title, kind, status, number of words). Use search_notebook "
        "to find passages in it."
    )
    args_model = GetNotebookArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def run(self, args: GetNotebookArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the notebook, or fail if it is not the student's."""
        found = await queries_of(self.bindings).get_notebook(
            ctx.actor.user_id, args.notebook_id
        )
        if found is None:
            raise ToolFailedError(support_details="notebook not found")
        return found
