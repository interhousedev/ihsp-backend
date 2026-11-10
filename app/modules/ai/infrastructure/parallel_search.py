"""Parallel as the primary web search, Exa as the fallback (and the deep partner).

`ParallelWebSearch` is the adapter of one `POST /v1/search`. `ParallelFirstWebSearch`
is the `WebSearchGateway` the platform uses: a normal search asks Parallel and goes to
Exa when Parallel fails, is rate limited, times out or finds nothing; a deep search
asks both and merges the pages, deduped by URL. Both name themselves in
`SearchReply.provider`, so the usage ledger and the logs say who answered.
"""

import asyncio
from typing import Any

from app.modules.ai.infrastructure.exa import ExaCallError
from app.modules.ai.infrastructure.exa_search import hits_of, unavailable_of
from app.modules.ai.infrastructure.parallel import ParallelApi
from app.settings import ParallelSettings
from app.settings_web_search import WebSearchSettings
from app.shared.contracts.web_search import (
    SearchCall,
    SearchNotice,
    SearchReply,
    WebHit,
    WebSearchGateway,
    WebSearchUnavailableError,
)
from app.shared.web_citations import url_key

import structlog

log = structlog.get_logger(__name__)

QUERY_CHARS = 200
LANGUAGES = {"uz": "Uzbek", "ru": "Russian", "en": "English"}


def parallel_body(call: SearchCall, config: ParallelSettings) -> dict[str, Any]:
    """The JSON body of one search. `max_results` lives in `advanced_settings`."""
    language = LANGUAGES.get(call.language, "English")
    advanced: dict[str, Any] = {
        "max_results": max(1, min(call.max_results, config.max_results))
    }
    excluded = list(dict.fromkeys(call.exclude_domains))
    if excluded:
        advanced["source_policy"] = {"exclude_domains": excluded}
    return {
        "objective": f"{call.query[:QUERY_CHARS]}. Prefer sources in {language}.",
        "search_queries": [call.query[:QUERY_CHARS]],
        "mode": config.search_mode,
        "advanced_settings": advanced,
    }


def _as_exa_results(results: list[Any]) -> list[Any]:
    """Parallel's pages in the shape `hits_of` reads (excerpts are the highlights)."""
    out: list[Any] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "url": item.get("url"),
                "title": item.get("title"),
                "highlights": item.get("excerpts"),
                "publishedDate": item.get("publish_date"),
            }
        )
    return out


class ParallelWebSearch:
    """Implements `WebSearchGateway` over a `ParallelApi` (real client or fake)."""

    def __init__(
        self,
        client: ParallelApi,
        config: WebSearchSettings,
        parallel: ParallelSettings,
    ) -> None:
        """Store the client and the settings of the search and of Parallel."""
        self.client = client
        self.config = config
        self.parallel = parallel

    async def search(self, call: SearchCall) -> SearchReply:
        """Run one search; a timeout is an empty reply with a notice.

        Raises:
            WebSearchUnavailableError: The key is refused, the service fails or its
                answer is unusable.
            WebSearchBusyError: Parallel answered 429.
        """
        try:
            data = await self.client.search(parallel_body(call, self.parallel))
        except ExaCallError as error:
            if error.timeout:
                log.warning(
                    "web_search_timeout",
                    provider="parallel",
                    timeout_seconds=self.parallel.timeout_seconds,
                )
                return SearchReply(
                    hits=(), usage={}, notice="timeout", provider="parallel"
                )
            raise unavailable_of(error, "Parallel") from error
        results = data.get("results")
        if not isinstance(results, list):
            log.warning("web_search_bad_answer", provider="parallel")
            raise WebSearchUnavailableError(
                support_details="Parallel answer without results"
            )
        reply = SearchReply(
            hits=hits_of(_as_exa_results(results), call, self.config),
            usage={},
            provider="parallel",
        )
        log.info(
            "web_search_done",
            provider="parallel",
            search_mode=self.parallel.search_mode,
            explain=call.explain,
            hits=len(reply.hits),
            search_id=data.get("search_id"),
        )
        return reply


class ParallelFirstWebSearch:
    """Parallel first, Exa when Parallel cannot answer; both for a deep search."""

    def __init__(self, parallel: WebSearchGateway, exa: WebSearchGateway) -> None:
        """Store the two providers."""
        self.parallel = parallel
        self.exa = exa

    async def search(self, call: SearchCall) -> SearchReply:
        """Run one search on the providers the call needs.

        Raises:
            WebSearchUnavailableError: Every asked provider failed.
        """
        if call.deep:
            return await self._both(call)
        primary, reason = await self._try_parallel(call)
        if primary is not None and primary.hits:
            return primary
        log.info("web_search_fallback", provider="parallel", to="exa", reason=reason)
        try:
            return await self.exa.search(call)
        except WebSearchUnavailableError:
            if primary is not None:
                return primary
            raise

    async def _try_parallel(self, call: SearchCall) -> tuple[SearchReply | None, str]:
        """Ask Parallel; return its reply (None on failure) and a fallback reason."""
        try:
            primary = await self.parallel.search(call)
        except WebSearchUnavailableError as error:
            return None, type(error).__name__
        return primary, str(primary.notice) if primary.notice else "empty"

    async def _both(self, call: SearchCall) -> SearchReply:
        outcomes = await asyncio.gather(
            self.parallel.search(call),
            self.exa.search(call),
            return_exceptions=True,
        )
        replies: list[SearchReply] = []
        first_error: WebSearchUnavailableError | None = None
        for outcome in outcomes:
            if isinstance(outcome, WebSearchUnavailableError):
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                replies.append(outcome)
        if not replies:
            assert first_error is not None
            raise first_error
        hits: list[WebHit] = []
        seen: set[str] = set()
        for reply in replies:
            for hit in reply.hits:
                key = url_key(hit.url)
                if key not in seen:
                    seen.add(key)
                    hits.append(hit)
        limit = 2 * call.max_results
        return SearchReply(
            hits=tuple(hits[:limit]),
            usage={},
            cost_micro=sum(reply.cost_micro for reply in replies),
            notice=None if hits else _notice_of(replies),
            provider="+".join(r.provider for r in replies if r.provider),
        )


def _notice_of(replies: list[SearchReply]) -> SearchNotice | None:
    """The first notice a provider gave (a timeout), when nothing was found."""
    return next((r.notice for r in replies if r.notice), None)
