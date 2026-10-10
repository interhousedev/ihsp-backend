"""Responses of the Administration insights."""

import datetime as dt

from pydantic import BaseModel


class DayCount(BaseModel):
    """One calendar day (Tashkent) and a count."""

    date: dt.date
    count: int


class SystemHealth(BaseModel):
    """What answers right now."""

    db: bool
    redis: bool
    queue_pending: int | None
    """Jobs read by a worker but not acknowledged yet; None without a queue."""
    queue_lag: int | None
    """Jobs waiting for a worker; None when Redis cannot say."""
    failed_logins_24h: int
    logins_24h: int


class StorageUsage(BaseModel):
    """Bytes and files of ready uploads."""

    bytes: int
    files: int
    by_scope: dict[str, int]


class UsageInsights(BaseModel):
    """Daily activity of the last 14 days (zero-filled)."""

    sign_ins: list[DayCount]
    ai_tokens: list[DayCount]
    storage: StorageUsage


class MarksInsights(BaseModel):
    """How many marks of each value (2 to 5) exist."""

    distribution: dict[str, int]


class InsightsResponse(BaseModel):
    """GET /v1/admin/insights."""

    generated_at: dt.datetime
    system: SystemHealth
    usage: UsageInsights
    marks: MarksInsights
