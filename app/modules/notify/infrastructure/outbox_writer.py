"""The real OutboxWriter: inserts notification drafts, ignoring duplicate keys."""

import json
from collections.abc import Iterator, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.notify.domain.notification_status import NotificationStatus
from app.modules.notify.infrastructure.tables import notifications_table
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

CHUNK_SIZE = 500  # asyncpg allows 32767 bind parameters per statement


def _default(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, set | frozenset):
        return sorted(value, key=str)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert dates, UUIDs and sets in a payload to JSON types."""
    converted: dict[str, Any] = json.loads(json.dumps(payload, default=_default))
    return converted


def _chunks(items: Sequence[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(items), CHUNK_SIZE):
        yield list(items[start : start + CHUNK_SIZE])


def _row(draft: NotificationDraft) -> dict[str, Any]:
    return {
        "id": new_id(),
        "user_id": draft.user_id,
        "type": draft.type.value,
        "payload": jsonable(draft.payload),
        "dedupe_key": draft.dedupe_key,
        "broadcast_id": draft.broadcast_id,
        "scheduled_at": draft.scheduled_at or sa.func.now(),
        "status": NotificationStatus.PENDING.value,
        "deliveries": {},
        "attempts": 0,
    }


async def write_notifications(
    session: AsyncSession, drafts: list[NotificationDraft]
) -> None:
    """Insert drafts as `pending`; a repeated `dedupe_key` is silently ignored."""
    if not drafts:
        return
    table = notifications_table()
    for chunk in _chunks([_row(draft) for draft in drafts]):
        stmt = (
            pg_insert(table)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=[table.c.dedupe_key])
        )
        await session.execute(stmt)
