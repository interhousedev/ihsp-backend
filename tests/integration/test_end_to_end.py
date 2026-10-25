"""Registration (fake EMIS) → backfill → regular sync a day later → Telegram message.

The whole `all` container runs over the test database, fakeredis, the fake clock, the
fake EMIS and the fake Telegram sender; nothing but the clock is stubbed in between.
"""

import json
from uuid import UUID

from app.bootstrap.container import Container
from app.modules.identity.domain.telegram_link import TelegramLink
from app.modules.identity.infrastructure.emis.fake import FAKE_PASSWORD
from app.modules.notify.infrastructure.fake_sender import OUTBOX_KEY
from tests.integration.conftest import ContainerFactory, IntegrationWorld

from fakeredis.aioredis import FakeRedis

TELEGRAM_USER_ID = 777001
MAX_DAYS = 6


async def _register(container: Container, world: IntegrationWorld) -> UUID:
    emis = container.identity.emis
    started = await emis.register_start.execute(
        emis_login="student01", emis_password=FAKE_PASSWORD, ip=None, locale="ru"
    )
    await emis.register_email_code.execute(
        registration_token=started.registration_token, email="student01@ihsu.uz"
    )
    registered = await emis.register_complete.execute(
        registration_token=started.registration_token,
        password="StudentDemo1",
        email_code=world.email.last_code or "",
        confirm_import_match=True,
        login_challenge=None,
        ip=None,
        user_agent=None,
    )
    return registered.user_id


async def _link_telegram(container: Container, user_id: UUID) -> None:
    async with container.identity.auth.uow_factory() as uow:
        await uow.telegram_links.add(
            TelegramLink(
                telegram_user_id=TELEGRAM_USER_ID, user_id=user_id, first_name="Ali"
            )
        )
        await uow.commit()


async def _messages(redis: FakeRedis) -> list[dict[str, object]]:
    return [json.loads(line) for line in await redis.lrange(OUTBOX_KEY, 0, -1)]


async def test_registered_student_gets_a_marks_message_after_the_next_sync(
    make_container: ContainerFactory, world: IntegrationWorld, redis: FakeRedis
) -> None:
    """SYNC-4/SYNC-5, BOT-11: backfill is silent, a later sync tells about new marks."""
    container = await make_container("all")
    user_id = await _register(container, world)
    await _link_telegram(container, user_id)

    assert "academic.backfill_student" in world.kicker.names()
    await container.academic.marks.backfill_student.execute(user_id)
    await container.notify.dispatch_due.execute()
    assert await _messages(redis) == []  # the backfill never alerts

    messages: list[dict[str, object]] = []
    for _ in range(MAX_DAYS):
        world.clock.advance(hours=24)
        outcome = await container.academic.marks.sync_student.execute(user_id)
        assert outcome.status == "ok"
        report = await container.notify.dispatch_due.execute()
        messages = await _messages(redis)
        if messages:
            assert report.sent >= 1
            break

    assert messages, "no marks message in six days of the fake EMIS"
    assert messages[0]["chat_id"] == TELEGRAM_USER_ID
    assert world.kicker.names().count("notify.dispatch_due") >= 1
