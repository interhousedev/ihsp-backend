"""Ports of the usage ledger: the writer and the reader of the reports."""

from datetime import datetime
from typing import Protocol

from app.modules.ai.domain.usage import GroupTotals, Totals, UsageEvent, UserTotals


class UsageSink(Protocol):
    """Writes ledger events; a failure is logged by the sink, never raised."""

    async def write(self, event: UsageEvent) -> None:
        """Insert one event."""
        ...


class FreeUsage(Protocol):
    """Notes a request answered without a paid call (stored pages, the query cache)."""

    async def note_free(self, *, task: str, model: str) -> None:
        """Record a zero-cost event of `task`; `model` is ``local`` or ``cache``."""
        ...


class UsageReader(Protocol):
    """Aggregates the ledger for the admin reports (times are aware datetimes)."""

    async def totals(self, start: datetime, end: datetime) -> Totals:
        """The sums of the events in [start, end)."""
        ...

    async def grouped(
        self, start: datetime, end: datetime, group_by: str
    ) -> list[GroupTotals]:
        """The sums per group key and feature.

        The key is a day, task, model, role, feature or user.
        """
        ...

    async def top_users(
        self, start: datetime, end: datetime, limit: int
    ) -> list[UserTotals]:
        """The users with the largest cost in [start, end), largest first."""
        ...
