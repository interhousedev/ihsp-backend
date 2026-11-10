"""Deterministic Parallel client for development and tests (`PARALLEL__MODE=fake`).

It answers in Parallel's own JSON shape (`results` with `url`, `title`, `excerpts`), so
the adapter that reads the real answers reads these too. The pages are the same three
Wikipedia search pages the fake Exa gives, one per platform language. A request without
`search_queries` is refused like the real API does (HTTP 422).
"""

from typing import Any
from urllib.parse import quote_plus

from app.modules.ai.infrastructure.exa import ExaCallError

_WIKIS = (("uz", "Uzbek"), ("ru", "Russian"), ("en", "English"))


class FakeParallelClient:
    """Answers every search with the same three pages for the query."""

    async def search(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return up to `advanced_settings.max_results` pages (3 at most)."""
        queries = body.get("search_queries")
        if not isinstance(queries, list) or not queries:
            raise ExaCallError(status=422, details="search_queries is required")
        query = str(queries[0])[:100]
        settings = body.get("advanced_settings") or {}
        limit = settings.get("max_results") if isinstance(settings, dict) else None
        count = limit if isinstance(limit, int) and limit > 0 else len(_WIKIS)
        results = [
            {
                "url": (
                    f"https://{code}.wikipedia.org/w/index.php"
                    f"?search={quote_plus(query)}"
                ),
                "title": f"{name} Wikipedia: {query[:60]}",
                "publish_date": None,
                "excerpts": [f"(fake) A general article on {query}."],
            }
            for code, name in _WIKIS[:count]
        ]
        return {"search_id": "fake", "results": results, "warnings": [], "usage": []}
