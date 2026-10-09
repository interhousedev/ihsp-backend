"""Web Push routes: config and the caller's device subscriptions."""

from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.push import ROUTERS
from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.infrastructure.tables import push_subscriptions_table
from app.modules.notify.wiring import NotifyServices, build
from app.settings import PushSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.db.uow_testing import noop_audit_writer
from app.shared.i18n.core import I18nCore
from app.shared.rate_limit import RateLimiter
from app.shared.wiring import ModuleDeps
from tests.conftest import HttpClientFactory
from tests.factories.notify import AUTH, P256DH, make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.files import FakeFilesApi
from tests.fakes.notify.identity import FakeIdentityDirectory
from tests.fakes.notify.links import FakeLinksApi
from tests.fakes.notify.push_sender import FakePushSender
from tests.fakes.notify.schedule import FakeScheduleQueries
from tests.fakes.notify.telegram_sender import FakeTelegramSender
from tests.fakes.tasks import FakeTaskKicker

import pytest
import sqlalchemy as sa
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PUBLIC_KEY = "BF-9bFMfqAmQ6TYgBFjiw6BHjB3d6nyMeSywyUqzS77qWp3V-4IJIN3SoSVtwUwXPYwZIi8IkIOHR1tYM88DUxk"  # noqa: E501
ENDPOINT = "https://fcm.googleapis.com/fcm/send/device-1"


def _services(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    enabled: bool,
) -> tuple[NotifyServices, FakeIdentityDirectory]:
    push = PushSettings(
        enabled=enabled,
        vapid_public_key=PUBLIC_KEY if enabled else None,
        vapid_private_key="x" if enabled else None,  # type: ignore[arg-type]
    )
    deps = ModuleDeps(
        settings=settings.model_copy(update={"push": push}),
        clock=clock,
        redis=redis,
        sessionmaker=sessionmaker,
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
        push=FakePushSender() if enabled else None,
    )
    return services, identity


class Api:
    """A client logged in as one teacher (any role may subscribe)."""

    def __init__(self, client: Any, actor: Actor, session: AsyncSession) -> None:
        self.client = client
        self.actor = actor
        self.session = session

    async def rows(self) -> list[dict[str, Any]]:
        table = push_subscriptions_table()
        result = await self.session.execute(sa.select(table))
        return [dict(r) for r in result.mappings().all()]

    def body(self, endpoint: str = ENDPOINT, **extra: Any) -> dict[str, Any]:
        return {"endpoint": endpoint, "keys": {"p256dh": P256DH, "auth": AUTH}, **extra}


@pytest.fixture
async def api(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    http_client: HttpClientFactory,
) -> Api:
    services, identity = _services(
        settings, clock, redis, kicker, i18n, sessionmaker_in_tx, enabled=True
    )
    user = identity.add_user(make_user(Role.TEACHER))
    actor = Actor(user_id=user.id, roles=frozenset({Role.TEACHER}))
    client = await http_client(
        ROUTERS, overrides={get_actor: lambda: actor}, notify=services
    )
    return Api(client, actor, db_session)


async def test_config_gives_the_public_key_when_push_is_on(api: Api) -> None:
    """The browser needs the VAPID key to subscribe."""
    response = await api.client.get("/v1/push/config")

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "vapid_public_key": PUBLIC_KEY}


async def test_config_says_disabled_without_a_key_when_push_is_off(
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    http_client: HttpClientFactory,
) -> None:
    """PUSH__ENABLED=false: the app hides the switch."""
    services, identity = _services(
        settings, clock, redis, kicker, i18n, sessionmaker_in_tx, enabled=False
    )
    user = identity.add_user(make_user(Role.STUDENT))
    actor = Actor(user_id=user.id, roles=frozenset({Role.STUDENT}))
    client = await http_client(
        ROUTERS, overrides={get_actor: lambda: actor}, notify=services
    )

    response = await client.get("/v1/push/config")

    assert response.json() == {"enabled": False, "vapid_public_key": None}


async def test_subscribe_returns_201_with_the_id_and_stores_the_row(api: Api) -> None:
    """The subscription belongs to the caller."""
    response = await api.client.post(
        "/v1/me/push-subscriptions",
        json=api.body(user_agent="Mozilla/5.0 (X11) Chrome/130"),
    )

    assert response.status_code == 201
    (row,) = await api.rows()
    assert response.json() == {"id": str(row["id"])}
    assert row["user_id"] == api.actor.user_id
    assert (row["endpoint"], row["p256dh"], row["auth"]) == (ENDPOINT, P256DH, AUTH)
    assert row["user_agent"] == "Mozilla/5.0 (X11) Chrome/130"
    assert row["failures"] == 0


async def test_subscribing_twice_updates_one_row(api: Api) -> None:
    """Upsert by endpoint: the browser may re-register on every visit."""
    first = await api.client.post("/v1/me/push-subscriptions", json=api.body())
    second = await api.client.post(
        "/v1/me/push-subscriptions", json=api.body(user_agent="new agent")
    )

    assert first.json() == second.json()
    (row,) = await api.rows()
    assert row["user_agent"] == "new agent"


async def test_an_endpoint_known_for_someone_else_moves_to_the_caller(
    api: Api,
) -> None:
    """A shared computer: the last person to sign in owns the subscription."""
    previous = UUID(int=7)
    await api.session.execute(
        sa.insert(push_subscriptions_table()).values(
            id=UUID(int=1),
            user_id=previous,
            endpoint=ENDPOINT,
            p256dh=P256DH,
            auth=AUTH,
            failures=3,
        )
    )

    response = await api.client.post("/v1/me/push-subscriptions", json=api.body())

    assert response.status_code == 201
    (row,) = await api.rows()
    assert (row["id"], row["user_id"], row["failures"]) == (
        UUID(int=1),
        api.actor.user_id,
        0,
    )


async def test_browser_extras_such_as_expiration_time_are_ignored(api: Api) -> None:
    """`PushSubscription.toJSON()` includes expirationTime."""
    response = await api.client.post(
        "/v1/me/push-subscriptions", json=api.body(expirationTime=None)
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"endpoint": "http://fcm.googleapis.com/x"}, "endpoint"),
        ({"endpoint": "https://169.254.169.254/latest"}, "endpoint"),
        ({"keys": {"p256dh": "AAAA", "auth": AUTH}}, "p256dh"),
        ({"keys": {"p256dh": P256DH, "auth": "AAAA"}}, "auth"),
    ],
)
async def test_unacceptable_subscriptions_are_refused(
    api: Api, body: dict[str, Any], field: str
) -> None:
    """The endpoint is a URL the server will call; the keys must decode."""
    response = await api.client.post(
        "/v1/me/push-subscriptions", json={**api.body(), **body}
    )

    assert response.status_code == 422
    assert response.json()["type"] == "notify/invalid-push-subscription"
    assert await api.rows() == []


async def test_a_body_without_keys_is_a_validation_error(api: Api) -> None:
    """The shape is checked before the rules."""
    response = await api.client.post(
        "/v1/me/push-subscriptions", json={"endpoint": ENDPOINT}
    )

    assert response.status_code == 422


async def test_delete_removes_the_callers_subscription(api: Api) -> None:
    """Switching push off on this device."""
    await api.client.post("/v1/me/push-subscriptions", json=api.body())

    response = await api.client.request(
        "DELETE", "/v1/me/push-subscriptions", json={"endpoint": ENDPOINT}
    )

    assert response.status_code == 204 and response.content == b""
    assert await api.rows() == []


async def test_delete_is_idempotent_and_ignores_other_peoples_endpoints(
    api: Api,
) -> None:
    """A second delete is fine; a stranger's subscription stays."""
    await api.session.execute(
        sa.insert(push_subscriptions_table()).values(
            id=UUID(int=2),
            user_id=UUID(int=9),
            endpoint=ENDPOINT,
            p256dh=P256DH,
            auth=AUTH,
        )
    )

    first = await api.client.request(
        "DELETE", "/v1/me/push-subscriptions", json={"endpoint": ENDPOINT}
    )
    again = await api.client.request(
        "DELETE", "/v1/me/push-subscriptions", json={"endpoint": ENDPOINT}
    )

    assert (first.status_code, again.status_code) == (204, 204)
    assert len(await api.rows()) == 1


async def test_an_eleventh_device_replaces_the_oldest(
    api: Api, clock: FixedClock
) -> None:
    """Ten devices per person."""
    for n in range(11):
        clock.advance(minutes=1)
        endpoint = f"https://fcm.googleapis.com/fcm/send/device-{n}"
        await api.client.post("/v1/me/push-subscriptions", json=api.body(endpoint))

    endpoints = {row["endpoint"] for row in await api.rows()}
    assert len(endpoints) == 10
    assert "https://fcm.googleapis.com/fcm/send/device-0" not in endpoints


async def test_every_route_needs_a_login(
    http_client: HttpClientFactory,
    settings: Settings,
    clock: FixedClock,
    redis: FakeRedis,
    kicker: FakeTaskKicker,
    i18n: I18nCore,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> None:
    """GEN-7: no token, no push."""
    services, _ = _services(
        settings, clock, redis, kicker, i18n, sessionmaker_in_tx, enabled=True
    )
    client = await http_client(ROUTERS, notify=services)

    config = await client.get("/v1/push/config")
    subscribe = await client.post("/v1/me/push-subscriptions", json={})
    delete = await client.request("DELETE", "/v1/me/push-subscriptions", json={})

    assert [r.status_code for r in (config, subscribe, delete)] == [401, 401, 401]
