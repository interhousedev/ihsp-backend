"""Unit of work against a real PostgreSQL transaction."""

from app.shared.db.uow import AfterCommit, SqlUnitOfWork
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType
from tests.fakes.outbox import InMemoryOutbox

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker


@pytest.fixture
async def probe(db_connection: AsyncConnection) -> AsyncConnection:
    """A temp table to prove commits and rollbacks (dropped with the outer rollback)."""
    await db_connection.execute(text("CREATE TEMP TABLE uow_probe (v int)"))
    return db_connection


async def rows(connection: AsyncConnection) -> int:
    """Count rows in the probe table."""
    result = await connection.execute(text("SELECT count(*) FROM uow_probe"))
    return int(result.scalar_one())


def make_uow(
    sessionmaker: async_sessionmaker[AsyncSession],
    outbox: InMemoryOutbox,
    hook: AfterCommit | None = None,
) -> SqlUnitOfWork:
    """Build a unit of work with the in-memory writers."""
    return SqlUnitOfWork(
        sessionmaker,
        outbox.write_notifications,
        outbox.write_audit,
        hook,
    )


def draft() -> NotificationDraft:
    """A notification draft."""
    return NotificationDraft(
        user_id=new_id(),
        type=NotificationType.MARKS,
        payload={},
        dedupe_key="k",
    )


async def test_commit_writes_data_outbox_and_audit(
    probe: AsyncConnection, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """GEN-8: one commit stores the change, the notifications and the audit events."""
    outbox = InMemoryOutbox()
    notification, audit = draft(), AuditDraft(type="user.created")

    async with make_uow(sessionmaker_in_tx, outbox) as uow:
        await uow.session.execute(text("INSERT INTO uow_probe VALUES (1)"))
        uow.notify(notification)
        uow.audit(audit)
        await uow.commit()

    assert await rows(probe) == 1
    assert outbox.notifications == [notification]
    assert outbox.audits == [audit]


async def test_an_exception_rolls_back_and_writes_nothing(
    probe: AsyncConnection, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """GEN-8: a failing use case leaves no data, no outbox and no audit rows."""
    outbox = InMemoryOutbox()

    with pytest.raises(RuntimeError):
        async with make_uow(sessionmaker_in_tx, outbox) as uow:
            await uow.session.execute(text("INSERT INTO uow_probe VALUES (1)"))
            uow.notify(draft())
            uow.audit(AuditDraft(type="x"))
            raise RuntimeError("boom")

    assert await rows(probe) == 0
    assert outbox.notifications == []
    assert outbox.audits == []


async def test_leaving_without_commit_rolls_back(
    probe: AsyncConnection, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """Only commit() stores changes."""
    outbox = InMemoryOutbox()

    async with make_uow(sessionmaker_in_tx, outbox) as uow:
        await uow.session.execute(text("INSERT INTO uow_probe VALUES (1)"))

    assert await rows(probe) == 0


async def test_after_commit_hooks_run_only_after_a_commit(
    probe: AsyncConnection, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """Tasks are kicked after the data is safe, never on a rollback."""
    outbox = InMemoryOutbox()
    ran: list[int] = []

    async def hook() -> None:
        ran.append(await rows(probe))

    with pytest.raises(RuntimeError):
        async with make_uow(sessionmaker_in_tx, outbox) as uow:
            uow.after_commit(hook)
            raise RuntimeError("boom")
    assert ran == []

    async with make_uow(sessionmaker_in_tx, outbox) as uow:
        await uow.session.execute(text("INSERT INTO uow_probe VALUES (1)"))
        uow.after_commit(hook)
        assert ran == []
        await uow.commit()

    assert ran == [1]


async def test_outbox_hook_runs_only_when_notifications_were_written(
    probe: AsyncConnection, sessionmaker_in_tx: async_sessionmaker[AsyncSession]
) -> None:
    """The dispatcher is woken only when there is something to dispatch."""
    outbox = InMemoryOutbox()
    woken: list[bool] = []

    async def wake() -> None:
        woken.append(True)

    async with make_uow(sessionmaker_in_tx, outbox, wake) as uow:
        await uow.commit()
    assert woken == []

    async with make_uow(sessionmaker_in_tx, outbox, wake) as uow:
        uow.notify(draft())
        await uow.commit()

    assert woken == [True]
