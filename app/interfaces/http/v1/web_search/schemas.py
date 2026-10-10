"""Response models of web search, shared by the assistant and notebook routes."""

from datetime import datetime
from typing import Literal, Self

from app.shared.contracts.web_search import WebQuota, WebResult

from pydantic import BaseModel, ConfigDict


class WebResultResponse(BaseModel):
    """`WebResult`: a page the web search found, numbered for the `⟦w1⟧` chips."""

    model_config = ConfigDict(from_attributes=True)

    n: int
    title: str
    url: str
    site: str
    snippet: str
    why: str
    cited: bool
    origin: Literal["web", "db"] = "web"
    """`db`: from the platform's own database, shown as "Из базы IHSP"."""

    @classmethod
    def from_result(cls, result: WebResult) -> Self:
        """Build from the stored result."""
        return cls(**result.model_dump())


class WebQuotaResponse(BaseModel):
    """`WebSearchStatus`: whether web search is on and today's searches.

    `remaining` is `limit - used` (never below 0). A Discover `deep` run costs
    `deep_cost` searches, every other search one. When `enabled` is false clients
    hide the toggle and Discover.
    """

    enabled: bool
    used: int
    limit: int
    remaining: int
    resets_at: datetime
    max_results: int
    deep_cost: int

    @classmethod
    def from_quota(cls, quota: WebQuota) -> Self:
        """Build from the quota."""
        return cls(
            enabled=quota.enabled,
            used=quota.used,
            limit=quota.limit,
            remaining=quota.remaining,
            resets_at=quota.resets_at,
            max_results=quota.max_results,
            deep_cost=quota.deep_cost,
        )
