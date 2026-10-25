"""Ports: item statistics in PostgreSQL and the Redis counters they come from."""

from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.enums import ItemStatus, ReportReason
from app.modules.library.domain.taxonomy_stats import DayCounters


class StatsRepository(Protocol):
    """Daily counters per item (`item_stats`) and the numbers built on them."""

    async def upsert_day(
        self, item_id: UUID, day: date, opens: int, readers: int, offline_saves: int
    ) -> None:
        """Set the counters of the item on the day (a repeat changes nothing)."""
        ...

    async def totals(self, start: date, end: date) -> tuple[int, int]:
        """`(opens, readers)` over the days; daily readers of each item add up."""
        ...

    async def top_items(
        self, start: date, end: date, limit: int
    ) -> list[tuple[UUID, int]]:
        """`(item id, opens)` of the most opened items in the window."""
        ...

    async def item_status_counts(self) -> dict[ItemStatus, int]:
        """How many items are in each status (statuses without items are absent)."""
        ...

    async def report_counts(
        self, since: datetime, until: datetime
    ) -> dict[ReportReason, int]:
        """Reports filed in `[since, until)` by reason (any status)."""
        ...

    async def uploads_by_day(self, since: datetime, until: datetime) -> dict[date, int]:
        """Materials created in `[since, until)` per UTC day (empty days absent)."""
        ...

    async def subject_ids_with_materials(self) -> set[UUID]:
        """Subjects that have a published book or material."""
        ...


class StatsCounters(Protocol):
    """The Redis side: counters written by `StatsRecorder`, read by the rollup."""

    async def day(self, day: date) -> dict[UUID, DayCounters]:
        """Counters of every item that was opened or saved on the day."""
        ...

    async def discard(self, day: date, item_ids: list[UUID]) -> None:
        """Delete the day's counters and reader sets of the items."""
        ...

    async def no_results(self, day: date, limit: int) -> dict[str, int]:
        """The most frequent searches without results on the day: `{query: count}`."""
        ...
