"""Read side of the usage analytics: request stats, spend and daily matrix."""

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol
from uuid import UUID

RequestGroup = Literal["request", "day", "user", "pipeline"]
SpendGroup = Literal["day", "request", "user"]


@dataclass(frozen=True, slots=True)
class RequestStatsRow:
    """Averages and totals of one group: a request, a day, a user or a pipeline."""

    key: str
    calls: int
    failed: int
    avg_prompt_tokens: float
    avg_prompt_chars: float
    avg_answer_chars: float
    avg_output_tokens: float
    avg_tool_calls: float
    cost_micro: int


@dataclass(frozen=True, slots=True)
class SpendRow:
    """Spend of one group; `user_id` is set only when grouping by user."""

    key: str
    cost_micro: int
    calls: int
    users: int
    user_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SpendDailyRow:
    """Spend of one day and one request (`request_id` is `other` for the tail)."""

    day: str
    request_id: str
    cost_micro: int
    calls: int


class AiAnalyticsReader(Protocol):
    """Reads the usage ledger for the admin analytics pages and MCP tools."""

    async def request_stats(
        self,
        start: date,
        end: date,
        request_id: str | None,
        pipeline: str | None,
        user_id: UUID | None,
        group_by: RequestGroup,
    ) -> list[RequestStatsRow]:
        """Averages and totals grouped as asked."""
        ...

    async def spend(
        self,
        start: date,
        end: date,
        by: SpendGroup,
        request_id: str | None,
        user_id: UUID | None,
        limit: int,
    ) -> list[SpendRow]:
        """Spend grouped as asked, most expensive first."""
        ...

    async def spend_daily(
        self,
        start: date,
        end: date,
        request_id: str | None,
        user_id: UUID | None,
    ) -> list[SpendDailyRow]:
        """Spend per day and request; the twenty costliest requests, the rest folded."""
        ...
