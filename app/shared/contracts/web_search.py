"""Web search contracts (provider: ai module; consumers: assistant chat, notebooks).

Two levels. `WebSearchGateway` is the port of one search call (OpenRouter in
production, a fake in tests). `WebSearchApi` is what the other modules use: it checks
the feature switch, spends the daily quota, runs the search (one call for `chat` and
`fast`, a plan, several calls and a ranking for `deep`) and gives the hits back.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.shared.actor import Actor
from app.shared.ai_tasks import ModelProfile
from app.shared.base_error import BaseError, NotFoundError, RateLimitedError

from pydantic import BaseModel, ConfigDict

WebSearchKind = Literal["chat", "fast", "deep"]
DiscoverMode = Literal["fast", "deep"]


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


class WebResult(WebHit):
    """A hit stored on a message: numbered `1..n`, `cited` when the answer uses it."""

    n: int
    cited: bool = False


@dataclass(frozen=True, slots=True)
class WebQuota:
    """The student's searches today."""

    enabled: bool
    used: int
    limit: int
    resets_at: datetime
    max_results: int
    deep_cost: int

    @property
    def remaining(self) -> int:
        """Searches left today."""
        return max(self.limit - self.used, 0)


@dataclass(frozen=True, slots=True)
class WebSearchOutcome:
    """The hits of one search request, what was searched and the quota afterwards."""

    hits: tuple[WebHit, ...]
    queries: tuple[str, ...]
    quota: WebQuota
    web_skipped: bool = False


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
    """The pages one call found and the model tokens it used."""

    hits: tuple[WebHit, ...]
    usage: dict[str, int]


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
        self, actor: Actor, *, query: str, locale: str, kind: WebSearchKind = "chat"
    ) -> WebSearchOutcome:
        """Spend the quota and search.

        `chat` and `fast` cost one search, `deep` costs `web_search_deep_queries`. A
        provider failure gives the spent searches back.

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
