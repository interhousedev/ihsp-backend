"""Notification center routes (WEB-27, UF-WEB-15)."""

from datetime import timedelta
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.notifications import ROUTERS
from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.wiring import NotifyServices, build
from app.settings import Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer
from app.shared.i18n.core import I18nCore
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.conftest import HttpClientFactory
from tests.factories.notify import NOW, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.links import FakeLinksApi
from tests.fakes.notify.schedule import FakeScheduleQueries
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.fakes.tasks import FakeTaskKicker
from tests.notify.db import insert_notification

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def notify_services(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> tuple[NotifyServices, FakeIdentityDirectory]:
    deps = ModuleDeps(
        settings=settings,
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker_in_tx,
        kicker=kicker,
        rate_limiter=RateLimiter(redis),
        i18n=i18n,
        outbox_writer=write_notifications,
        audit_writer=noop_audit_writer,
        outbox_committed_hook=None,
    )
    identity = FakeIdentityDirectory()
    services = build(
        deps,
        identity=identity,
        schedule=FakeScheduleQueries(),
        links=FakeLinksApi(),
        mail=object(),  # type: ignore[arg-type]
        files=FakeFilesApi(),
        telegram=FakeTelegramSender(),
    )
    return services, identity


class Api:
    """A client logged in as one student."""

    def __init__(self, client: Any, actor: Actor) -> None:
        self.client = client
        self.actor = actor


@pytest.fixture
async def api(
    http_client: HttpClientFactory,
    notify_services: tuple[NotifyServices, FakeIdentityDirectory],
) -> Api:
    services, identity = notify_services
    user = identity.add_user(make_user(Role.STUDENT, locale="en"))
    actor = Actor(user_id=user.id, roles=frozenset({Role.STUDENT}))
    client = await http_client(
        ROUTERS, overrides={get_actor: lambda: actor}, notify=services
    )
    return Api(client, actor)


async def test_list_returns_described_items_with_the_contract_fields(
    api: Api, db_session: AsyncSession
) -> None:
    """WEB-27: NotificationItem {id, type, title, body, link, created_at, read_at}."""
    await insert_notification(
        db_session,
        api.actor.user_id,
        "broadcast",
        payload={"title": "Exams", "text": "<b>Monday</b>"},
        created_at=NOW - timedelta(minutes=1),
    )
    await insert_notification(db_session, api.actor.user_id, "emis_reauth")

    response = await api.client.get("/v1/notifications")

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    first, second = body["items"]
    assert set(first) == {
        "id",
        "type",
        "title",
        "body",
        "link",
        "created_at",
        "read_at",
    }
    assert (first["type"], first["title"]) == ("emis_reauth", "EMIS password needed")
    assert first["link"].endswith("/security/emis/")
    assert (second["title"], second["body"], second["link"]) == (
        "Exams",
        "Monday",
        None,
    )


async def test_filter_announcements_returns_only_broadcasts(
    api: Api, db_session: AsyncSession
) -> None:
    """UF-WEB-15 step 2: the Announcements tab."""
    await insert_notification(db_session, api.actor.user_id, "marks")
    await insert_notification(
        db_session, api.actor.user_id, "broadcast", payload={"title": "T", "text": "x"}
    )

    response = await api.client.get("/v1/notifications?filter=announcements")

    assert [i["type"] for i in response.json()["items"]] == ["broadcast"]


async def test_unknown_filter_is_a_validation_error(api: Api) -> None:
    """WEB-27: only all, activity and announcements."""
    response = await api.client.get("/v1/notifications?filter=everything")

    assert response.status_code == 422


async def test_cursor_pagination(api: Api, db_session: AsyncSession) -> None:
    """WEB-27: limit and next_cursor."""
    for minutes in range(3):
        await insert_notification(
            db_session, api.actor.user_id, created_at=NOW - timedelta(minutes=minutes)
        )

    first = (await api.client.get("/v1/notifications?limit=2")).json()
    second = (
        await api.client.get(f"/v1/notifications?limit=2&cursor={first['next_cursor']}")
    ).json()

    assert len(first["items"]) == 2 and first["next_cursor"]
    assert len(second["items"]) == 1 and second["next_cursor"] is None


async def test_unread_count_read_and_read_all(
    api: Api, db_session: AsyncSession
) -> None:
    """UF-WEB-15: the bell count, opening an item, Mark all as read."""
    ids = [await insert_notification(db_session, api.actor.user_id) for _ in range(3)]

    count = await api.client.get("/v1/notifications/unread-count")
    read = await api.client.post(f"/v1/notifications/{ids[0]}/read")
    after_one = await api.client.get("/v1/notifications/unread-count")
    read_all = await api.client.post("/v1/notifications/read-all")
    after_all = await api.client.get("/v1/notifications/unread-count")

    assert count.json() == {"count": 3}
    assert read.status_code == 204 and read.content == b""
    assert after_one.json() == {"count": 2}
    assert read_all.status_code == 204
    assert after_all.json() == {"count": 0}


async def test_reading_an_unknown_notification_is_not_found(
    api: Api, db_session: AsyncSession
) -> None:
    """GEN-7: someone else's id looks like a missing one."""
    foreign = await insert_notification(db_session, new_id())

    response = await api.client.post(f"/v1/notifications/{foreign}/read")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "notify/not-found"


async def test_requests_without_a_token_are_unauthorized(
    http_client: HttpClientFactory,
    notify_services: tuple[NotifyServices, FakeIdentityDirectory],
) -> None:
    """GEN-7: the center needs a logged-in user."""
    client = await http_client(ROUTERS, notify=notify_services[0])

    response = await client.get("/v1/notifications")

    assert response.status_code == 401
