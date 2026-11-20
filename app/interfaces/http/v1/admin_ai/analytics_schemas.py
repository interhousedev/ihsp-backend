"""Bodies of /v1/admin/ai/analytics (money in micro-USD)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RequestStatsOut(BaseModel):
    """Averages and totals of one group of calls."""

    key: str = Field(description="Request id, day, user id or pipeline.")
    calls: int
    failed: int
    avg_prompt_tokens: float
    avg_prompt_chars: float
    avg_answer_chars: float
    avg_output_tokens: float
    avg_tool_calls: float
    cost_micro: int


class RequestTotalsOut(BaseModel):
    """The totals over every group (averages weighted by calls)."""

    calls: int
    failed: int
    avg_prompt_tokens: float
    avg_prompt_chars: float
    avg_answer_chars: float
    avg_output_tokens: float
    avg_tool_calls: float
    cost_micro: int


class RequestStatsResponse(BaseModel):
    """Per-group statistics and their totals."""

    items: list[RequestStatsOut]
    totals: RequestTotalsOut


class SpendUserOut(BaseModel):
    """The user of a spend row grouped by user."""

    id: str
    full_name: str
    role: str | None


class SpendOut(BaseModel):
    """Spend of one day, request or user."""

    key: str
    cost_micro: int
    calls: int
    users: int
    user: SpendUserOut | None


class SpendResponse(BaseModel):
    """Spend rows, most expensive first."""

    items: list[SpendOut]
    total_cost_micro: int


class SpendDailyOut(BaseModel):
    """Spend of one request on one day (`other` folds the tail)."""

    day: str
    request_id: str
    cost_micro: int
    calls: int


class SpendDailyResponse(BaseModel):
    """The day x request matrix."""

    items: list[SpendDailyOut]


class PromptSizeOut(BaseModel):
    """The size of one prompt version (0 is the built-in text)."""

    task: str
    name: str
    locale: str
    version: int
    source: Literal["code", "admin"]
    chars: int
    tokens_est: int
    created_at: datetime
    active: bool


class PromptSizesResponse(BaseModel):
    """Prompt sizes per slot and version."""

    items: list[PromptSizeOut]
