"""SQL store of the usage ledger: writes, and the retention purge."""

from datetime import datetime

from app.modules.ai.domain.usage import UsageEvent
from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow
from app.shared.ids import new_id

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = structlog.get_logger(__name__)

PURGE_BATCH = 5000


class SqlUsageStore:
    """Implements `UsageSink` and the retention purge over the sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Keep the sessionmaker."""
        self.sessionmaker = sessionmaker

    async def write(self, event: UsageEvent) -> None:
        """Insert one event in its own short transaction; a failure is only logged."""
        try:
            async with self.sessionmaker() as session:
                session.add(
                    UsageEventRow(
                        id=new_id(),
                        occurred_at=event.occurred_at,
                        user_id=event.user_id,
                        role=event.role,
                        task=event.task,
                        feature=event.feature,
                        model=event.model,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cached_tokens=event.cached_tokens,
                        reasoning_tokens=event.reasoning_tokens,
                        cost_micro=event.cost_micro,
                        success=event.success,
                        error=event.error,
                    )
                )
                await session.commit()
        except Exception:
            log.exception("usage_event_write_failed", task=event.task)

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete the events older than `cutoff` in batches; return how many went."""
        removed = 0
        while True:
            async with self.sessionmaker() as session:
                ids = select(UsageEventRow.id).where(UsageEventRow.occurred_at < cutoff)
                ids = ids.limit(PURGE_BATCH)
                result = await session.execute(
                    delete(UsageEventRow).where(UsageEventRow.id.in_(ids))
                )
                await session.commit()
                count = int(getattr(result, "rowcount", 0) or 0)
            removed += count
            if count < PURGE_BATCH:
                return removed
