"""A scripted WebSearchGateway and a scripted JSON model for the web search tests."""

from dataclasses import dataclass
from typing import Any

from app.modules.ai.application.web_search import WebSearchService
from app.settings import Settings
from app.shared.clock import Clock
from app.shared.contracts.ai import AiProviderError
from app.shared.contracts.web_search import (
    SearchCall,
    SearchReply,
    WebHit,
    WebSearchUnavailableError,
)
from tests.fakes.ai.stores import InMemorySearchQuotaStore


def page(n: int, *, topic: str = "photosynthesis", why: str = "") -> WebHit:
    """A hit about a topic, distinct per number."""
    return WebHit(
        title=f"{topic.title()} {n}",
        url=f"https://school{n}.example.org/{topic}",
        site=f"school{n}.example.org",
        snippet=f"Everything about {topic}, part {n}.",
        why=why,
    )


class ScriptedWebSearch:
    """Pops queued replies (or errors); without a script it finds three pages.

    The default pages are distinct for every call (`school1..3` for the first call of
    a test, `school4..6` for the next, ...), so merged results can be told apart.
    """

    def __init__(self) -> None:
        """Start with no script and no calls."""
        self.calls: list[SearchCall] = []
        self.queue: list[SearchReply | Exception] = []
        self._next = 1

    def push(self, *items: SearchReply | Exception) -> None:
        """Queue replies or errors for the next calls."""
        self.queue.extend(items)

    def fail_next(self) -> None:
        """Make the next call fail like a provider outage."""
        self.queue.append(WebSearchUnavailableError(support_details="HTTP 503"))

    async def search(self, call: SearchCall) -> SearchReply:
        """Record the call and return the next scripted reply."""
        self.calls.append(call)
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        first = self._next
        self._next += 3
        hits = tuple(
            page(n, why="It explains the topic." if call.explain else "")
            for n in range(first, first + 3)
        )
        return SearchReply(hits=hits[: call.max_results], usage={"input": 1000})


class ScriptedJson:
    """Implements `complete_json` for the plan and the ranking; records requests."""

    def __init__(self) -> None:
        """Start with nothing queued."""
        self.queue: list[dict[str, Any] | Exception] = []
        self.requests: list[dict[str, Any]] = []

    def push(self, *items: dict[str, Any] | Exception) -> None:
        """Queue documents (or errors) for the next calls."""
        self.queue.extend(items)

    async def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        """Record the request and return the next document."""
        self.requests.append(kwargs)
        if not self.queue:
            raise AiProviderError(support_details="nothing scripted")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"data": item, "text": "", "usage": {"input": 10, "output": 5}}


@dataclass
class WebRig:
    """The real search service over a scripted search, a scripted JSON model and a
    memory counter: what the other modules' tests plug in as `WebSearchApi`."""

    service: WebSearchService
    search: ScriptedWebSearch
    json: ScriptedJson
    store: InMemorySearchQuotaStore

    @classmethod
    def build(cls, settings: Settings, clock: Clock) -> "WebRig":
        """Wire the service over the fakes."""
        search, scripted, store = (
            ScriptedWebSearch(),
            ScriptedJson(),
            InMemorySearchQuotaStore(),
        )
        service = WebSearchService(
            store=store,
            gateway=search,
            llm=scripted,  # type: ignore[arg-type]  # only complete_json is used
            clock=clock,
            settings=settings,
        )
        return cls(service, search, scripted, store)
