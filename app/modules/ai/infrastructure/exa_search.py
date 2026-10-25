"""Exa adapter of the WebSearchGateway: one `POST /search` per search, hits from it.

Exa ranks the pages for the query and returns an excerpt of each (`text`). For a
Discover search it also returns the passages that answer the query (`highlights`):
the first one is the "why this page" sentence, so a search needs no model call. Only
pages of the answer become hits; a page on a blocked domain is dropped here too, in
case Exa ignores `excludeDomains`. Exa has no language filter: the query goes as the
student wrote it.
"""

from datetime import date
from typing import Any
from urllib.parse import urlsplit

from app.modules.ai.infrastructure.exa import ExaApi, ExaCallError
from app.settings import ExaSettings
from app.settings_web_search import WebSearchSettings
from app.shared.contracts.web_search import (
    SearchCall,
    SearchReply,
    WebHit,
    WebSearchBusyError,
    WebSearchUnavailableError,
)
from app.shared.web_citations import clean_text, site_of, url_blocked, url_key

import structlog

log = structlog.get_logger(__name__)

TITLE_CHARS = 200
WHY_CHARS = 220
MAX_URL_CHARS = 2048
HIGHLIGHT_SENTENCES = 2
HIGHLIGHTS_PER_URL = 2
DEFAULT_BUSY_SECONDS = 60
MAX_BUSY_SECONDS = 3600
MICRO = 1_000_000


def search_body(call: SearchCall, config: ExaSettings) -> dict[str, Any]:
    """The JSON body of one search. The key is never in it (it is a header)."""
    contents: dict[str, Any] = {"text": {"maxCharacters": config.text_max_characters}}
    if call.explain:
        contents["highlights"] = {
            "numSentences": HIGHLIGHT_SENTENCES,
            "highlightsPerUrl": HIGHLIGHTS_PER_URL,
            "query": call.query,
        }
    body: dict[str, Any] = {
        "query": call.query,
        "type": config.search_type,
        "numResults": call.max_results,
        "contents": contents,
    }
    excluded = list(dict.fromkeys(call.exclude_domains))
    if excluded:
        body["excludeDomains"] = excluded
    return body


def hits_of(
    results: list[Any], call: SearchCall, config: WebSearchSettings
) -> tuple[WebHit, ...]:
    """The distinct, allowed pages of an answer, best first, at most `max_results`."""
    blocked = (*config.blocked_domains, *call.exclude_domains)
    hits: list[WebHit] = []
    seen: set[str] = set()
    for item in results:
        hit = _hit(item, call, config)
        if hit is None or url_blocked(hit.url, blocked):
            continue
        key = url_key(hit.url)
        if key in seen:
            continue
        seen.add(key)
        hits.append(hit)
        if len(hits) == call.max_results:
            break
    return tuple(hits)


def cost_micro_of(data: dict[str, Any]) -> int:
    """`costDollars.total` of an answer in millionths of a dollar; 0 when missing."""
    cost = data.get("costDollars")
    total = cost.get("total") if isinstance(cost, dict) else None
    if isinstance(total, bool) or not isinstance(total, int | float) or total < 0:
        return 0
    return round(total * MICRO)


def _hit(item: Any, call: SearchCall, config: WebSearchSettings) -> WebHit | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    site = site_of(url)
    if (
        not site
        or len(url) > MAX_URL_CHARS
        or urlsplit(url).scheme not in {"http", "https"}
    ):
        return None
    highlights = _texts(item.get("highlights"))
    text = str(item.get("text") or "")
    why = clean_text(highlights[0], WHY_CHARS) if call.explain and highlights else ""
    return WebHit(
        title=clean_text(str(item.get("title") or ""), TITLE_CHARS) or site,
        url=url,
        site=site,
        snippet=clean_text(text or " ".join(highlights), config.snippet_chars),
        why=why,
        published_date=_date_of(item.get("publishedDate")),
    )


def _date_of(value: Any) -> date | None:
    """The day of an ISO timestamp from Exa (`2025-03-01T...`), or None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _texts(value: Any) -> list[str]:
    """The non-empty strings of a list (Exa's highlights), in order."""
    if not isinstance(value, list):
        return []
    return [text for text in value if isinstance(text, str) and text.strip()]


class ExaWebSearch:
    """Implements `WebSearchGateway` over an `ExaApi` (the real client or the fake)."""

    def __init__(
        self, client: ExaApi, config: WebSearchSettings, exa: ExaSettings
    ) -> None:
        """Store the Exa client and the settings of the search and of Exa."""
        self.client = client
        self.config = config
        self.exa = exa

    async def search(self, call: SearchCall) -> SearchReply:
        """Run one search.

        A timeout is an empty reply with a notice; other failures are
        `WebSearchUnavailableError`, or `WebSearchBusyError` for a rate limit.

        Raises:
            WebSearchUnavailableError: The key is refused, the service fails or its
                answer is unusable.
            WebSearchBusyError: Exa answered 429; `seconds` says when to try again.
        """
        try:
            data = await self.client.search(search_body(call, self.exa))
        except ExaCallError as error:
            if error.timeout:
                log.warning(
                    "web_search_timeout", timeout_seconds=self.exa.timeout_seconds
                )
                return SearchReply(hits=(), usage={}, notice="timeout")
            raise _unavailable(error) from error
        results = data.get("results")
        if not isinstance(results, list):
            log.warning("web_search_bad_answer")
            raise WebSearchUnavailableError(
                support_details="Exa answer without results"
            )
        reply = SearchReply(
            hits=hits_of(results, call, self.config),
            usage={},
            cost_micro=cost_micro_of(data),
        )
        # Never the query or the pages: counts, the charge and Exa's request id.
        log.info(
            "web_search_done",
            provider="exa",
            search_type=self.exa.search_type,
            explain=call.explain,
            hits=len(reply.hits),
            cost_micro=reply.cost_micro,
            request_id=data.get("requestId"),
        )
        return reply


def _unavailable(error: ExaCallError) -> WebSearchUnavailableError:
    """The platform error of a failed Exa call; the key is never logged or shown."""
    if error.status == 429:
        seconds = _busy_seconds(error.retry_after)
        log.warning("web_search_rate_limited", retry_after=seconds)
        return WebSearchBusyError(
            params={"seconds": seconds}, support_details="Exa HTTP 429"
        )
    if error.status in {401, 403}:
        log.error("web_search_key_refused", status=error.status)
        return WebSearchUnavailableError(
            support_details=f"Exa HTTP {error.status}: the API key is refused"
        )
    log.warning("web_search_failed", status=error.status, reason=error.details)
    if error.status:
        return WebSearchUnavailableError(
            support_details=f"Exa HTTP {error.status}: {error.details}"
        )
    return WebSearchUnavailableError(support_details=f"Exa {error.details}")


def _busy_seconds(retry_after: float | None) -> int:
    """Seconds to tell the student: Exa's `Retry-After` within sane bounds."""
    if retry_after is None:
        return DEFAULT_BUSY_SECONDS
    return max(1, min(int(retry_after), MAX_BUSY_SECONDS))
