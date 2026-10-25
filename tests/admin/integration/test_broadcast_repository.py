"""SQL broadcast repository and delivery reader against PostgreSQL (ADM-11)."""

from datetime import timedelta
from uuid import UUID

from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.broadcast import (
    Broadcast,
    BroadcastStats,
    BroadcastStatus,
    CreatedVia,
)
from app.modules.admin.domain.errors import BroadcastNotFoundError
from app.modules.admin.infrastructure.repositories.broadcast_repository import (
    SqlBroadcastRepository,
)
from app.modules.admin.infrastructure.repositories.delivery_reader import (
    SqlDeliveryReader,
)
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.factories.notify import NOW
from tests.notify.db import insert_notification

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def make_broadcast(**kwargs: object) -> Broadcast:
    values: dict[str, object] = {
        "id": new_id(),
        "author_id": new_id(),
        "created_via": CreatedVia.UI,
        "title": "Exams",
        "text": "<b>Monday</b>",
        "audience": Audience(roles=[Role.STUDENT], semesters=[1, 2]),
        "created_at": NOW,
        "media_file_ids": [new_id()],
    }
    values.update(kwargs)
    return Broadcast(**values)  # type: ignore[arg-type]


@pytest.fixture
def repo(db_session: AsyncSession) -> SqlBroadcastRepository:
    return SqlBroadcastRepository(db_session)


async def test_broadcast_round_trips_with_audience_media_and_stats(
    repo: SqlBroadcastRepository,
) -> None:
    """ADM-11: every field is stored and read back."""
    broadcast = make_broadcast(
        audience=Audience(
            everyone=False, roles=[Role.STUDENT], group_ids=[new_id()], semesters=[1, 2]
        ),
        scheduled_at=NOW + timedelta(hours=1),
        status=BroadcastStatus.SCHEDULED,
    )
    await repo.add(broadcast)

    broadcast.start_sending(7)
    await repo.save(broadcast)
    loaded = await repo.get(broadcast.id)

    assert loaded == broadcast
    assert loaded.stats == BroadcastStats(total=7, sent=0, failed=0, blocked=0)


async def test_missing_broadcast_is_not_found(repo: SqlBroadcastRepository) -> None:
    """ADM-11: unknown ids are a 404."""
    with pytest.raises(BroadcastNotFoundError):
        await repo.get(new_id())


async def test_list_page_filters_by_status_and_uses_a_keyset_cursor(
    repo: SqlBroadcastRepository,
) -> None:
    """ADM-11: newest first, optional status, no overlap between pages."""
    author = new_id()
    made = [
        make_broadcast(author_id=author, created_at=NOW - timedelta(minutes=m))
        for m in (3, 2, 1)
    ]
    made[1].status = BroadcastStatus.SCHEDULED
    for b in made:
        await repo.add(b)

    first = await repo.list_page(status=None, before=None, limit=2)
    second = await repo.list_page(
        status=None, before=(first[-1].created_at, first[-1].id), limit=2
    )
    drafts = await repo.list_page(status=BroadcastStatus.DRAFT, before=None, limit=10)

    newest_first = [b.id for b in reversed(made)]
    mine = [b.id for b in first + second if b.author_id == author]
    assert mine == newest_first
    assert {b.id for b in drafts if b.author_id == author} == {made[0].id, made[2].id}


async def test_claim_scheduled_returns_due_scheduled_broadcasts_only(
    repo: SqlBroadcastRepository,
) -> None:
    """UF-ADM-08 4a: the minute task picks up broadcasts whose time came."""
    due = make_broadcast(
        status=BroadcastStatus.SCHEDULED, scheduled_at=NOW - timedelta(minutes=1)
    )
    waiting = make_broadcast(
        status=BroadcastStatus.SCHEDULED, scheduled_at=NOW + timedelta(minutes=1)
    )
    draft = make_broadcast()
    for b in (due, waiting, draft):
        await repo.add(b)

    claimed = await repo.claim_scheduled(NOW)

    assert [b.id for b in claimed if b.id in {due.id, waiting.id, draft.id}] == [due.id]


async def test_list_sending_returns_only_sending_broadcasts(
    repo: SqlBroadcastRepository,
) -> None:
    """ADM-11: the finish task looks at broadcasts being delivered."""
    sending = make_broadcast(status=BroadcastStatus.SENDING)
    sent = make_broadcast(status=BroadcastStatus.SENT)
    await repo.add(sending)
    await repo.add(sent)

    ids = {b.id for b in await repo.list_sending()}

    assert sending.id in ids and sent.id not in ids


async def test_delivery_counts_come_from_the_notifications(
    db_session: AsyncSession,
) -> None:
    """BOT-22: blocked users are counted as blocked, not failed."""
    reader = SqlDeliveryReader(db_session)
    broadcast_id = new_id()

    async def add(status: str, deliveries: dict[str, str] | None = None) -> UUID:
        return await insert_notification(
            db_session,
            new_id(),
            "broadcast",
            status=status,
            broadcast_id=broadcast_id,
            deliveries=deliveries or {},
        )

    for _ in range(3):
        await add("sent", {"1": "sent"})
    await add("failed", {"2": "failed"})
    await add("skipped", {"3": "blocked"})
    await add("skipped", {})  # no Telegram account: neither failed nor blocked
    await add("pending")
    await add("partial", {"4": "failed"})
    await add("sending")
    await insert_notification(db_session, new_id(), "broadcast")  # another broadcast

    counts = await reader.counts(broadcast_id)

    assert (counts.total, counts.sent, counts.failed) == (9, 3, 1)
    assert (counts.blocked, counts.open) == (1, 3)
