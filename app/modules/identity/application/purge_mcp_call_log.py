"""Job `identity.purge_mcp_call_log`: drop traces past the retention setting (B1)."""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.clock import Clock

BATCH = 5000


@dataclass(frozen=True, slots=True)
class PurgeMcpCallLog:
    """Deletes in short transactions so tool calls never wait on it."""

    uow_factory: UowFactory
    clock: Clock
    retention_days: int = 90

    async def execute(self) -> int:
        """Remove rows past the retention period; return how many."""
        cutoff = self.clock.now() - timedelta(days=self.retention_days)
        total = 0
        while True:
            async with self.uow_factory() as uow:
                removed = await uow.mcp_calls.purge_before(cutoff, limit=BATCH)
                await uow.commit()
            total += removed
            if removed < BATCH:
                return total
