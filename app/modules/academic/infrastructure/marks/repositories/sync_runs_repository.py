"""SQL repository of EMIS sync run summaries."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.marks.records import SyncRunRecord
from app.modules.academic.infrastructure.orm.sync_run import SyncRun
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


class SqlSyncRunsRepository:
    """Implements SyncRunsRepository on an open session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session

    async def create(self, started_at: dt.datetime) -> UUID:
        """Insert a running run and return its id."""
        run_id = new_id()
        await self.session.execute(
            sa.insert(SyncRun).values(
                id=run_id, started_at=started_at, status="running", stats={}
            )
        )
        return run_id

    async def finish(
        self,
        run_id: UUID,
        *,
        finished_at: dt.datetime,
        status: str,
        stats: dict[str, int],
    ) -> None:
        """Close a run with its status and statistics."""
        await self.session.execute(
            sa.update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(finished_at=finished_at, status=status, stats=stats)
        )

    async def running_since(self, cutoff: dt.datetime) -> bool:
        """Return True if a run started after the cutoff is still running."""
        stmt = sa.select(
            sa.exists().where(SyncRun.status == "running", SyncRun.started_at > cutoff)
        )
        return bool((await self.session.execute(stmt)).scalar())

    async def status_of(self, run_id: UUID) -> str | None:
        """Return the status of a run, None for an unknown id."""
        stmt = sa.select(SyncRun.status).where(SyncRun.id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_page(
        self, *, before: tuple[dt.datetime, UUID] | None, limit: int
    ) -> list[SyncRunRecord]:
        """Return runs newest first, after the cursor position."""
        stmt = sa.select(
            SyncRun.id,
            SyncRun.started_at,
            SyncRun.finished_at,
            SyncRun.status,
            SyncRun.stats,
        )
        if before is not None:
            stmt = stmt.where(
                sa.tuple_(SyncRun.started_at, SyncRun.id)
                < sa.tuple_(
                    sa.literal(before[0], sa.DateTime(timezone=True)),
                    sa.literal(before[1], sa.Uuid()),
                )
            )
        stmt = stmt.order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(limit)
        return [
            SyncRunRecord(
                id=r.id,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                stats={k: int(v) for k, v in (r.stats or {}).items()},
            )
            for r in (await self.session.execute(stmt)).all()
        ]
