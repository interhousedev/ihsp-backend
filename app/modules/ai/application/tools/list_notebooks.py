"""Tool: the student's notebooks."""

from typing import Any

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.notebook_common import queries_of
from app.modules.ai.domain.tool_args import ToolArgs

LIST_LIMIT = 50


class ListNotebooksArgs(ToolArgs):
    """No arguments."""


class ListNotebooks(ReadTool[ListNotebooksArgs]):
    """The student's notebooks."""

    name = "list_notebooks"
    description = (
        "List the student's notebooks (collections of sources with cited answers "
        "and study materials): id, title, emoji, number of sources and when it was "
        "last opened."
    )
    args_model = ListNotebooksArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def run(self, args: ListNotebooksArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the notebooks, last opened first."""
        rows = await queries_of(self.bindings).list_notebooks(
            ctx.actor.user_id, LIST_LIMIT
        )
        return capped(rows)
