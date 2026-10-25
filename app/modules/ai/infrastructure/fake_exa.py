"""Deterministic Exa client for development and tests (`IHSP_EXA__MODE=fake`).

It answers in Exa's own JSON shape, so the adapter that reads the real answers reads
these too. The results are three Wikipedia search pages for the query, one per
platform language: real, public pages, so adding one as a URL source in development
works with the real fetcher. The costs are the ones given to the constructor (0 by
default: nothing is spent in development).
"""

from typing import Any
from urllib.parse import quote_plus

_WIKIS = (("uz", "Uzbek"), ("ru", "Russian"), ("en", "English"))


class FakeExaClient:
    """Answers every search with the same three pages for the query."""

    def __init__(self, *, cost_dollars: float = 0.0) -> None:
        """Keep the cost the fake reports for each call."""
        self.cost_dollars = cost_dollars

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return up to `numResults` pages, with highlights when they are asked for."""
        query = str(body.get("query") or "")[:100]
        limit = _count(body.get("numResults"))
        wants_highlights = "highlights" in (body.get("contents") or {})
        results: list[dict[str, Any]] = []
        for code, name in _WIKIS[:limit]:
            item: dict[str, Any] = {
                "title": f"{name} Wikipedia: {query[:60]}",
                "url": (
                    f"https://{code}.wikipedia.org/w/index.php"
                    f"?search={quote_plus(query)}"
                ),
                "text": f"(fake) Search results about {query}.",
            }
            if wants_highlights:
                item["highlights"] = [f"(fake) A general article on {query}."]
                item["highlightScores"] = [0.5]
            results.append(item)
        return {
            "requestId": "fake",
            "results": results,
            "costDollars": {"total": self.cost_dollars},
        }


def _count(value: object) -> int:
    """`numResults` as a count of pages, 3 when it is missing or not a whole number."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return min(value, len(_WIKIS))
    return len(_WIKIS)
