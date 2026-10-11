"""Web search contracts (provider: ai module; consumers: assistant chat, notebooks).

Two levels. `WebSearchGateway` is the port of one search call (OpenRouter in
production, a fake in tests). `WebSearchApi` is what the other modules use: it checks
the feature switch, spends the daily quota, runs the search (one call for `chat` and
`fast`, a plan, several calls and a ranking for `deep`) and gives the hits back.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from app.shared.actor import Actor
from app.shared.ai_tasks import ModelProfile
from app.shared.base_error import BaseError, NotFoundError, RateLimitedError

from pydantic import BaseModel, ConfigDict

WebSearchKind = Literal["chat", "fast", "deep"]
DiscoverMode = Literal["fast", "deep"]
# Why a search gave no pages although the provider answered: `timeout` (Exa was too
# slow). The searches are given back, the answer or the list says so.
SearchNotice = Literal["timeout"]


class WebSearchDisabledError(NotFoundError):
    """Web search is switched off (`FEATURES__WEB_SEARCH=false`) or the quota is 0."""

    code = "web-search/disabled"
    message_key = "web-search-disabled"


class WebSearchQuotaError(RateLimitedError):
    """Today's searches are used up (params: limit, left, needed, resets_at)."""

    code = "web-search/quota-exceeded"
    message_key = "web-search-quota-exceeded"


class WebSearchUnavailableError(BaseError):
    """The search provider failed; nothing was spent."""

    code = "web-search/unavailable"
    status = 503
    message_key = "web-search-unavailable"


class WebSearchBusyError(WebSearchUnavailableError):
    """The provider is busy (rate limit); nothing was spent (params: seconds)."""

    code = "web-search/busy"
    status = 429
    message_key = "web-search-busy"


class WebHit(BaseModel):
    """One page the search found: what the student sees and the answer may cite."""

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    site: str
    snippet: str
    why: str = ""
    origin: Literal["web", "db"] = "web"
    ref_kind: Literal["library_item", "notebook_source"] | None = None
    """What a `db` hit is, so Discover can add it by reference instead of by URL."""
    ref_id: str | None = None
    """`db`: found in the platform's own database ("из базы"), not on the web."""
    published_date: date | None = None
    """When the page was published, when the provider says so."""


class WebResult(WebHit):
    """A hit stored on a message: numbered `1..n`, `cited` when the answer uses it."""

    n: int
    cited: bool = False


@dataclass(frozen=True, slots=True)
class WebQuota:
    """The searches of one user today; `limit` is None for an unlimited user (staff)."""

    enabled: bool
    used: int
    limit: int | None
    resets_at: datetime
    max_results: int
    deep_cost: int

    @property
    def remaining(self) -> int | None:
        """Searches left today; None when unlimited."""
        if self.limit is None:
            return None
        return max(self.limit - self.used, 0)


@dataclass(frozen=True, slots=True)
class WebSearchOutcome:
    """The hits of one search request, what was searched and the quota afterwards."""

    hits: tuple[WebHit, ...]
    queries: tuple[str, ...]
    quota: WebQuota
    web_skipped: bool = False
    cost_micro: int = 0
    """What the provider charged for the searches, in millionths of a dollar."""
    notice: SearchNotice | None = None
    sources: tuple[str, ...] = ()
    """Where the hits came from: `db` (platform), `local` (stored pages), `cache` (an
    earlier answer to the same query), `exa` (a search that spent the quota)."""


@dataclass(frozen=True, slots=True)
class SearchCall:
    """One call to the search provider."""

    query: str
    language: str  # uz | ru | en: the language to prefer in results
    max_results: int
    explain: bool  # ask for a one-sentence reason per page
    profile: ModelProfile
    exclude_domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SearchReply:
    """The pages one call found, its charge and the model tokens it used."""

    hits: tuple[WebHit, ...]
    usage: dict[str, int]
    cost_micro: int = 0
    """What the provider charged for this call, in millionths of a dollar."""
    notice: SearchNotice | None = None


class WebSearchGateway(Protocol):
    """One web search call."""

    async def search(self, call: SearchCall) -> SearchReply:
        """Search and return the hits (blocked domains removed, duplicates merged).

        Raises:
            WebSearchUnavailableError: The provider failed.
        """
        ...


class WebSearchApi(Protocol):
    """Web search for the modules that answer or find sources (ai module)."""

    async def quota(self, actor: Actor) -> WebQuota:
        """Today's quota of the actor (`enabled=False` when the feature is off)."""
        ...

    async def search(
        self,
        actor: Actor,
        *,
        query: str,
        locale: str,
        kind: WebSearchKind = "chat",
        known_urls: frozenset[str] = frozenset(),
    ) -> WebSearchOutcome:
        """Answer from the stored pages when they are enough, else spend the quota.

        `known_urls` are the normalised URLs the student already has (the notebook's
        sources, the chat's cited pages): they never count as new. When the stored
        pages give `web_search_local_min_new` new ones, Exa is not called and the quota
        is not spent. `chat` and `fast` cost one search, `deep` costs
        `web_search_deep_queries`. A provider failure gives the spent searches back.

        Raises:
            WebSearchDisabledError: The feature is off for everyone or this role.
            WebSearchQuotaError: Not enough searches are left today.
            WebSearchUnavailableError: The provider failed.
        """
        ...


@dataclass(frozen=True, slots=True)
class PlatformPassage:
    """A passage of the platform's database (library, shared or the user's sources)."""

    title: str
    url: str
    text: str
    site: str = "IHT"
    ref_kind: Literal["library_item", "notebook_source"] | None = None
    ref_id: str | None = None


class PlatformSearch(Protocol):
    """Hybrid (words and meaning) search over what the platform already holds."""

    async def search(
        self, actor: Actor, query: str, limit: int
    ) -> list[PlatformPassage]:
        """Passages the actor may read, best first (empty when nothing fits)."""
        ...
