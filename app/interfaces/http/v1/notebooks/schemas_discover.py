"""Request and response models of Discover (`POST /notebooks/{id}/discover`)."""

from typing import Literal, Self

from app.interfaces.http.v1.web_search.schemas import WebQuotaResponse
from app.modules.notebooks.application.discover_sources import (
    DiscoveredPage,
    DiscoverView,
)

from pydantic import BaseModel, Field


class DiscoverBody(BaseModel):
    """`POST /notebooks/{id}/discover`.

    `fast` is one web search; `deep` plans several queries, searches them and ranks
    the pages, and costs `deep_cost` of today's searches (`GET /ai/web-search`).
    """

    query: str = Field(min_length=1, max_length=2000)
    """A topic or a request; 2 to 300 characters after trimming (422 above that)."""

    mode: Literal["fast", "deep"] = "fast"


class DiscoverResultResponse(BaseModel):
    """`DiscoverResult`: a page to add as a URL source."""

    title: str
    url: str
    site: str
    snippet: str
    why: str
    already_added: bool
    """The notebook already has this page as a source."""

    @classmethod
    def from_page(cls, page: DiscoveredPage) -> Self:
        """Build from the found page."""
        return cls(**page.hit.model_dump(), already_added=page.already_added)


class DiscoverResponse(BaseModel):
    """`DiscoverResults`: ranked pages, what was searched and today's searches."""

    mode: Literal["fast", "deep"]
    queries: list[str]
    results: list[DiscoverResultResponse]
    quota: WebQuotaResponse

    @classmethod
    def from_view(cls, view: DiscoverView) -> Self:
        """Build from the use case view."""
        return cls(
            mode=view.mode,
            queries=list(view.queries),
            results=[DiscoverResultResponse.from_page(p) for p in view.results],
            quota=WebQuotaResponse.from_quota(view.quota),
        )
