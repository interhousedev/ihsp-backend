"""Deterministic WebSearchGateway for development (`OPENROUTER__MODE=fake`).

The three hits are Wikipedia search pages for the query in the three platform
languages. They are real, public pages, so adding one as a URL source in development
works with the real fetcher.
"""

from urllib.parse import quote_plus

from app.shared.contracts.web_search import SearchCall, SearchReply, WebHit

_WIKIS = (("uz", "Uzbek"), ("ru", "Russian"), ("en", "English"))


class FakeWebSearch:
    """Answers every query with the same three pages, the preferred language first."""

    async def search(self, call: SearchCall) -> SearchReply:
        """Return up to `call.max_results` Wikipedia search pages."""
        ordered = sorted(_WIKIS, key=lambda wiki: wiki[0] != call.language)
        hits = tuple(
            WebHit(
                title=f"{name} Wikipedia: {call.query[:60]}",
                url=(
                    f"https://{code}.wikipedia.org/w/index.php"
                    f"?search={quote_plus(call.query[:100])}"
                ),
                site=f"{code}.wikipedia.org",
                snippet=f"(fake) Search results about {call.query[:100]}.",
                why="(fake) A general article on the topic." if call.explain else "",
            )
            for code, name in ordered
        )[: call.max_results]
        return SearchReply(hits=hits, usage={"input": 0, "output": 0, "cached": 0})
