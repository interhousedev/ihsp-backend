"""Tool: search the passages of a notebook."""

from typing import Any
from uuid import UUID

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.application.tools.notebook_common import queries_of
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field


class SearchNotebookArgs(ToolArgs):
    """A notebook, a search phrase and how many passages to return."""

    notebook_id: UUID
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=8, ge=1, le=20)


class SearchNotebook(ReadTool[SearchNotebookArgs]):
    """Passages of a notebook's sources, best match first."""

    name = "search_notebook"
    description = (
        "Search the sources of one of the student's notebooks; returns the best "
        "matching passages (source id and title, passage number, page, text of up "
        "to 600 characters). Words are matched, not meaning, so try the key terms "
        "of the question. Cite the source title when you answer from a passage."
    )
    args_model = SearchNotebookArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound notebooks API."""
        self.bindings = bindings

    async def run(self, args: SearchNotebookArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the passages; an empty result still checks the notebook exists."""
        api = queries_of(self.bindings)
        rows = await api.search(
            ctx.actor.user_id, args.notebook_id, args.query, args.limit
        )
        if (
            not rows
            and await api.get_notebook(ctx.actor.user_id, args.notebook_id) is None
        ):
            raise ToolFailedError(support_details="notebook not found")
        return capped(rows)
