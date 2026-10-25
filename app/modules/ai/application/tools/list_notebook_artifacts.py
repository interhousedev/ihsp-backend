"""Tool: the Studio outputs of a notebook."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.notebook_common import queries_of
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs


class ListNotebookArtifactsArgs(ToolArgs):
    """A notebook."""

    notebook_id: UUID


class ListNotebookArtifacts(ReadTool[ListNotebookArtifactsArgs]):
    """Reports, mind maps, quizzes and other outputs of a notebook."""

    name = "list_notebook_artifacts"
    description = (
        "List the study materials generated in one of the student's notebooks "
        "(Studio): id, kind, title and status."
    )
    args_model = ListNotebookArtifactsArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def run(
        self, args: ListNotebookArtifactsArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        """Return the outputs; an empty list still checks the notebook exists."""
        api = queries_of(self.bindings)
        rows = await api.list_artifacts(ctx.actor.user_id, args.notebook_id)
        if (
            not rows
            and await api.get_notebook(ctx.actor.user_id, args.notebook_id) is None
        ):
            raise ToolFailedError(support_details="notebook not found")
        return capped(rows)
