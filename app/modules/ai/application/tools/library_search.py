"""Tool: search the library's books and articles (offered in the library app)."""

from typing import Any

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ReadTool, ToolContext
from app.modules.ai.application.tools.format import capped
from app.modules.ai.domain.tool_args import ToolArgs

from pydantic import Field


class SearchLibraryArgs(ToolArgs):
    """A search phrase and how many passages to return."""

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=6, ge=1, le=10)


class SearchLibrary(ReadTool[SearchLibraryArgs]):
    """Passages of the library's items, best match first."""

    name = "library_search"
    description = (
        "Use for questions about books and articles in the library; cite the title "
        "and url of each passage you use."
    )
    args_model = SearchLibraryArgs

    def __init__(self, bindings: LateBindings) -> None:
        """Store the late-bound library search."""
        self.bindings = bindings

    async def run(self, args: SearchLibraryArgs, ctx: ToolContext) -> dict[str, Any]:
        """Return the passages the actor may read (none while unbound)."""
        search = self.bindings.library_search
        if search is None:
            return capped([])
        found = await search.search(ctx.actor, args.query.strip(), args.limit)
        return capped(
            [
                {"title": p.title, "url": p.url, "text": p.text, "site": p.site}
                for p in found
            ]
        )
