"""Concurrent dispatchers share the queue without sending a row twice (GEN-8)."""

import asyncio
from collections import Counter
from typing import Any

from app.modules.notify.application import dispatch_due as dispatch_module
from app.modules.notify.application.dispatch_due import DispatchDue
from app.modules.notify.application.renderers.registry import RendererRegistry
from app.modules.notify.infrastructure.tables import notifications_table
from app.shared.contracts.notify import RenderContext, RenderedMessage
from app.shared.db.engine import make_sessionmaker
from app.shared.notifications import NotificationType
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.limiter import CountingLimiter
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.notify.db import insert_notification, uow_factory

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

ROWS = 12


class SlowSender(FakeTelegramSender):
    """Yields to the other dispatcher on every send."""

    async def send_message(
        self,
        chat_id: int,
        text_html: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> int:
        await asyncio.sleep(0.005)
        return await super().send_message(chat_id, text_html, buttons)


async def _hello(payload: dict[str, Any], ctx: RenderContext) -> RenderedMessage:
    return RenderedMessage(text_html="hello")


async def test_two_dispatchers_never_send_one_row_twice(
    engine: AsyncEngine, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GEN-8: FOR UPDATE SKIP LOCKED gives each row to exactly one dispatcher."""
    sessionmaker = make_sessionmaker(engine)
    identity = FakeIdentityDirectory()
    users = [identity.add_user(make_user(), 5000 + i) for i in range(ROWS)]
    async with sessionmaker() as session:
        for user in users:
            await insert_notification(session, user.id)
        await session.commit()
    monkeypatch.setattr(dispatch_module, "BATCH_SIZE", 3)
    sender = SlowSender()
    registry = RendererRegistry()
    registry.register(NotificationType.MARKS, _hello)

    def dispatcher() -> DispatchDue:
        return DispatchDue(
            uow_factory=uow_factory(sessionmaker),
            identity=identity,
            renderers=registry,
            sender=sender,
            limiter=CountingLimiter(),
            clock=clock,
        )

    try:
        first, second = await asyncio.gather(
            dispatcher().execute(), dispatcher().execute()
        )

        per_chat = Counter(m.chat_id for m in sender.messages())
        assert per_chat == Counter({5000 + i: 1 for i in range(ROWS)})
        assert first.claimed + second.claimed == ROWS
        assert first.sent + second.sent == ROWS
    finally:
        table = notifications_table()
        async with sessionmaker() as session:
            await session.execute(
                sa.delete(table).where(table.c.user_id.in_([u.id for u in users]))
            )
            await session.commit()
