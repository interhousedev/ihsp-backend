"""Fixtures of the schedule tests: the same services on fakes and on PostgreSQL."""

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_schedule import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.me_schedule import ROUTERS as ME_ROUTERS
from app.interfaces.http.v1.staff_groups import ROUTERS as STAFF_GROUP_ROUTERS
from app.shared.actor import Actor, Role
from tests.academic.schedule.env import Env, EnvKind, build_env
from tests.conftest import HttpClientFactory
from tests.factories import make_actor
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(params=["fake", "sql"])
def env(
    request: pytest.FixtureRequest,
    clock: FixedClock,
    kicker: FakeTaskKicker,
    redis: FakeRedis,
) -> Env:
    """The schedule services on in-memory fakes, then on PostgreSQL (same tests).

    A sync fixture: it may ask for the async `sessionmaker_in_tx` only outside the
    event loop, and only for the PostgreSQL variant.
    """
    kind: EnvKind = request.param
    maker: async_sessionmaker[AsyncSession] | None = None
    if kind == "sql":
        maker = request.getfixturevalue("sessionmaker_in_tx")
    return build_env(kind, clock=clock, kicker=kicker, redis=redis, maker=maker)


@pytest.fixture
def sql_env(
    clock: FixedClock,
    kicker: FakeTaskKicker,
    redis: FakeRedis,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> Env:
    """The schedule services on PostgreSQL only (for constraints and SQL queries)."""
    return build_env(
        "sql", clock=clock, kicker=kicker, redis=redis, maker=sessionmaker_in_tx
    )


@dataclass(slots=True)
class Api:
    """An HTTP client whose caller can be switched during a test."""

    client: AsyncClient
    holder: dict[str, Actor]

    def as_actor(self, actor: Actor) -> None:
        """Make the following requests as this actor."""
        self.holder["actor"] = actor

    def as_role(self, role: Role, *, user_id: UUID | None = None) -> Actor:
        """Make the following requests as a user with one role."""
        actor = make_actor(role, user_id=user_id)
        self.holder["actor"] = actor
        return actor


@pytest_asyncio.fixture
async def api(env: Env, http_client: HttpClientFactory) -> Api:
    """Every B3 router on a test app over the same services as `env`."""
    holder: dict[str, Actor] = {"actor": make_actor(Role.ADMIN)}
    routers = [*ADMIN_ROUTERS, *STAFF_GROUP_ROUTERS, *ME_ROUTERS]
    client = await http_client(
        routers,
        {get_actor: lambda: holder["actor"]},
        academic=SimpleNamespace(schedule=env.services),
    )
    return Api(client, holder)
