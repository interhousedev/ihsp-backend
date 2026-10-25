"""Tool: search the internet when the school data has nothing (one daily search).

With the limit `ai_ask_before_web_search` on (the default) a call is an approval
card: the student allows the search. Off, it runs at once like a read tool.
"""

import re
from typing import Any

from app.modules.ai.application.late_bindings import LateBindings
from app.modules.ai.application.tools.base import ToolContext, WriteTool
from app.modules.ai.domain.errors import ToolFailedError
from app.modules.ai.domain.tool_args import ToolArgs
from app.modules.ai.domain.tool_call import PreviewData
from app.shared.limits import LimitsProvider

from pydantic import field_validator

SNIPPET_CHARS = 500
QUERY_CHARS = 300
# A query leaves the school system for the open web, so links and addresses in it
# (a pasted URL, an e-mail of a person) are removed before the search and the card.
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def clean_query(raw: str) -> str:
    """The web query: no URLs or e-mail addresses, at most QUERY_CHARS characters."""
    text = _EMAIL.sub(" ", _URL.sub(" ", raw))
    return " ".join(text.split())[:QUERY_CHARS]


class SearchWebArgs(ToolArgs):
    """What to search for (a cleaned, length-capped query)."""

    query: str

    @field_validator("query", mode="before")
    @classmethod
    def _clean(cls, value: object) -> str:
        cleaned = clean_query(str(value or ""))
        if not cleaned:
            raise ValueError("the query is empty after cleaning")
        return cleaned


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
