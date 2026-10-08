"""Helpers for notify tests that use the real database."""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.notify.infrastructure.tables import notifications_table
from app.modules.notify.infrastructure.uow import SqlNotifyUnitOfWork
from app.shared.db.uow_testing import noop_audit_writer, noop_outbox_writer
from app.shared.ids import new_id
from tests.factories.notify import NOW

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def uow_factory(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[[], SqlNotifyUnitOfWork]:
    """A factory of SQL units of work with no-op outbox and audit writers."""

    def factory() -> SqlNotifyUnitOfWork:
        return SqlNotifyUnitOfWork(sessionmaker, noop_outbox_writer, noop_audit_writer)

    return factory


async def insert_notification(
    session: AsyncSession,
    user_id: UUID,
    notification_type: str = "marks",
    *,
    scheduled_at: datetime = NOW,
    created_at: datetime | None = None,
    **overrides: Any,
) -> UUID:
    """Insert one row with explicit times; `overrides` set any other column."""
    notification_id = new_id()
    values: dict[str, Any] = {
        "id": notification_id,
        "user_id": user_id,
        "type": notification_type,
        "payload": {},
        "dedupe_key": f"test:{notification_id}",
        "scheduled_at": scheduled_at,
        "created_at": created_at or scheduled_at,
        "status": "pending",
        "deliveries": {},
        "attempts": 0,
        **overrides,
    }
    await session.execute(sa.insert(notifications_table()).values(**values))
    return notification_id


async def fetch_row(session: AsyncSession, notification_id: UUID) -> dict[str, Any]:
    """Read one row as a dict."""
    table = notifications_table()
    result = await session.execute(
        sa.select(table).where(table.c.id == notification_id)
    )
    return dict(result.mappings().one())
