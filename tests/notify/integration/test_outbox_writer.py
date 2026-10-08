"""The real outbox writer: inserts and ignores repeated dedupe keys (GEN-8)."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.infrastructure.tables import notifications_table
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType
from tests.factories.notify import NOW

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def draft(
    key: str,
    *,
    user_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    scheduled_at: datetime | None = None,
    broadcast_id: UUID | None = None,
) -> NotificationDraft:
    return NotificationDraft(
        user_id=user_id or new_id(),
        type=NotificationType.MARKS,
        payload=payload or {},
        dedupe_key=key,
        scheduled_at=scheduled_at,
        broadcast_id=broadcast_id,
    )


async def rows(session: AsyncSession, key_prefix: str) -> list[dict[str, Any]]:
    table = notifications_table()
    result = await session.execute(
        sa.select(table).where(table.c.dedupe_key.like(f"{key_prefix}%"))
    )
    return [dict(row) for row in result.mappings()]


async def test_drafts_are_inserted_as_pending_and_due_immediately(
    db_session: AsyncSession,
) -> None:
    """GEN-8: the outbox row is pending, scheduled now, with no deliveries."""
    user = new_id()
    await write_notifications(db_session, [draft("w1:a", user_id=user)])

    (row,) = await rows(db_session, "w1:")

    assert row["user_id"] == user
    assert row["type"] == "marks"
    assert row["status"] == "pending"
    assert row["deliveries"] == {}
    assert row["attempts"] == 0
    assert row["scheduled_at"] is not None
    assert row["read_at"] is None


async def test_explicit_schedule_and_broadcast_id_are_stored(
    db_session: AsyncSession,
) -> None:
    """BOT-15: lesson links are written with their send time."""
    broadcast_id = new_id()
    await write_notifications(
        db_session,
        [draft("w2:a", scheduled_at=NOW, broadcast_id=broadcast_id)],
    )

    (row,) = await rows(db_session, "w2:")

    assert row["scheduled_at"] == NOW
    assert row["broadcast_id"] == broadcast_id


async def test_repeated_dedupe_key_is_ignored(db_session: AsyncSession) -> None:
    """GEN-8: the same event never produces two notifications."""
    user = new_id()
    await write_notifications(
        db_session, [draft("w3:k", user_id=user, payload={"v": 1})]
    )
    await write_notifications(
        db_session, [draft("w3:k", user_id=user, payload={"v": 2})]
    )

    (row,) = await rows(db_session, "w3:")

    assert row["payload"] == {"v": 1}


async def test_duplicates_inside_one_batch_are_ignored(
    db_session: AsyncSession,
) -> None:
    """GEN-8: a batch may repeat a key."""
    await write_notifications(
        db_session, [draft("w4:k"), draft("w4:k"), draft("w4:other")]
    )

    assert len(await rows(db_session, "w4:")) == 2


async def test_payload_with_uuid_and_date_is_stored_as_json(
    db_session: AsyncSession,
) -> None:
    """GEN-8: producers may put UUIDs and dates in payloads."""
    lesson = new_id()
    await write_notifications(
        db_session,
        [draft("w5:k", payload={"lesson_id": lesson, "date": date(2026, 10, 6)})],
    )

    (row,) = await rows(db_session, "w5:")

    assert row["payload"] == {"lesson_id": str(lesson), "date": "2026-10-06"}


async def test_large_batches_are_chunked(db_session: AsyncSession) -> None:
    """ADM-11: 1000 recipients fit in one call."""
    drafts = [draft(f"w6:{i}") for i in range(1200)]

    await write_notifications(db_session, drafts)

    assert len(await rows(db_session, "w6:")) == 1200


async def test_empty_list_writes_nothing(db_session: AsyncSession) -> None:
    """GEN-8: committing without notifications is cheap."""
    await write_notifications(db_session, [])

    assert await rows(db_session, "w7:") == []
