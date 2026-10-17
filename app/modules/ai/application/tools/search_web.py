"""Tool: search the internet when the school data has nothing (one daily search).

With the limit `ai_ask_before_web_search` on (the default) a call is an approval
card: the student allows the search. Off, it runs at once like a read tool.
"""

from typing import Any

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData
from app.shared.limits import LimitsProvider

from pydantic import Field

SNIPPET_CHARS = 500


class SearchWebArgs(ToolArgs):
    """What to search for."""

    query: str = Field(min_length=1, max_length=200)


class SearchWeb(WriteTool[SearchWebArgs]):
    """Pages of the internet for a query (spends one web search of the day)."""

    name = "search_web"
    description = (
        "Search the internet when the school data has nothing; returns pages "
        "(title, url, snippet). Cite the url."
    )
    args_model = SearchWebArgs

    def __init__(self, bindings: LateBindings, limits: LimitsProvider) -> None:
        """Store the late-bound web search and the runtime limits."""
        self.bindings = bindings
        self.limits = limits

    async def needs_approval(self, ctx: ToolContext) -> bool:
        """True while the limit `ai_ask_before_web_search` is on."""
        current = await self.limits.current()
        return bool(current.ai_ask_before_web_search)

    async def preview(self, args: SearchWebArgs, ctx: ToolContext) -> PreviewData:
        """Show the query the search would send."""
        return PreviewData(
            title_key="ai-preview-search-web", title_params={"query": args.query}
        )

    async def run(self, args: SearchWebArgs, ctx: ToolContext) -> dict[str, Any]:
        """Search and return the pages."""
        web = self.bindings.web
        if web is None:
            raise ToolFailedError(support_details="web search is unavailable")
        outcome = await web.search(ctx.actor, query=args.query, locale=ctx.locale)
        return {
            "pages": [
                {"title": h.title, "url": h.url, "snippet": h.snippet[:SNIPPET_CHARS]}
                for h in outcome.hits
            ]
        }
