"""Use case: delete the usage events older than the retention window (daily job)."""

from datetime import datetime, timedelta
from typing import Protocol

from app.shared.clock import Clock


class UsagePurger(Protocol):
    """Deletes the ledger events older than a moment."""

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete the events before `cutoff`; return how many went."""
        ...


class PurgeUsageEvents:
    """Keeps the ledger for `retention_days` (the admin reports need a year)."""

    def __init__(
        self, *, store: UsagePurger, clock: Clock, retention_days: int
    ) -> None:
        """Keep the store, the clock and the window."""
        self.store = store
        self.clock = clock
        self.retention_days = retention_days

    async def execute(self) -> int:
        """Remove the expired events; return how many were removed."""
        cutoff = self.clock.now() - timedelta(days=self.retention_days)
        return await self.store.purge_before(cutoff)
