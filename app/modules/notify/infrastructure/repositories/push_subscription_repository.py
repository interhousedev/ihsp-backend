"""SQL repository of Web Push subscriptions (Core statements)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from app.modules.notify.domain.push_subscription import PushSubscription
from app.modules.notify.infrastructure.tables import push_subscriptions_table
from app.shared.ids import new_id

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


def _to_entity(row: RowMapping) -> PushSubscription:
    return PushSubscription(
        id=row["id"],
        user_id=row["user_id"],
        endpoint=row["endpoint"],
        p256dh=row["p256dh"],
        auth=row["auth"],
        user_agent=row["user_agent"],
        created_at=row["created_at"],
        last_success_at=row["last_success_at"],
        failures=row["failures"] or 0,
    )


class SqlPushSubscriptionRepository:
    """Reads and writes subscription rows in the unit of work's session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind to the unit of work's session."""
        self.session = session
        self.table = push_subscriptions_table()

    async def upsert(
        self,
        *,
        user_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None,
        now: datetime,
    ) -> UUID:
        """Insert by endpoint; an existing endpoint moves to the user as a new one."""
        t = self.table
        insert = pg_insert(t).values(
            id=new_id(),
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            created_at=now,
            failures=0,
        )
        stmt = insert.on_conflict_do_update(
            index_elements=[t.c.endpoint],
            set_={
                "user_id": user_id,
                "p256dh": p256dh,
                "auth": auth,
                "user_agent": user_agent,
                "created_at": now,
                "failures": 0,
            },
        ).returning(t.c.id)
        return cast(UUID, (await self.session.execute(stmt)).scalar_one())

    async def trim(self, user_id: UUID, keep: int) -> int:
        """Delete the user's oldest rows beyond `keep`."""
        t = self.table
        newest = (
            sa.select(t.c.id)
            .where(t.c.user_id == user_id)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
            .limit(keep)
        )
        stmt = sa.delete(t).where(t.c.user_id == user_id, t.c.id.not_in(newest))
        result = cast(CursorResult[Any], await self.session.execute(stmt))
        return int(result.rowcount)

    async def delete_by_endpoint(self, user_id: UUID, endpoint: str) -> bool:
        """Delete the user's row with this endpoint."""
        t = self.table
        stmt = (
            sa.delete(t)
            .where(t.c.user_id == user_id, t.c.endpoint == endpoint)
            .returning(t.c.id)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def list_for_user(self, user_id: UUID) -> list[PushSubscription]:
        """Return the user's rows, oldest first."""
        t = self.table
        stmt = (
            sa.select(t).where(t.c.user_id == user_id).order_by(t.c.created_at, t.c.id)
        )
        result = await self.session.execute(stmt)
        return [_to_entity(row) for row in result.mappings().all()]

    async def delete_many(self, ids: Sequence[UUID]) -> None:
        """Delete rows by id."""
        if ids:
            await self.session.execute(
                sa.delete(self.table).where(self.table.c.id.in_(list(ids)))
            )

    async def record_success(self, ids: Sequence[UUID], now: datetime) -> None:
        """Set `last_success_at` and clear the failure counter."""
        if ids:
            await self.session.execute(
                sa.update(self.table)
                .where(self.table.c.id.in_(list(ids)))
                .values(last_success_at=now, failures=0)
            )

    async def record_failure(self, subscription_id: UUID) -> int:
        """Add one failure; return the count after (0 when the row is gone)."""
        t = self.table
        stmt = (
            sa.update(t)
            .where(t.c.id == subscription_id)
            .values(failures=t.c.failures + 1)
            .returning(t.c.failures)
        )
        return int((await self.session.execute(stmt)).scalar() or 0)
