"""Fixtures of the composition adapter tests."""

from collections.abc import Callable

from app.modules.academic.infrastructure.marks.uow import SqlMarksUnitOfWork
from tests.academic.schedule.env import Env, EnvKind, build_env
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
from fakeredis.aioredis import FakeRedis
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
    """The academic schedule services on PostgreSQL (rolled back after the test)."""
    return build_env(
        "sql", clock=clock, kicker=kicker, redis=redis, maker=sessionmaker_in_tx
    )


@pytest.fixture
def marks_uow_factory(sql_env: Env) -> Callable[[], SqlMarksUnitOfWork]:
    """A factory of marks units of work on the same database as `sql_env`."""
    assert sql_env.maker is not None
    assert sql_env.outbox is not None
    maker, outbox = sql_env.maker, sql_env.outbox

    def factory() -> SqlMarksUnitOfWork:
        return SqlMarksUnitOfWork(
            maker, outbox.write_notifications, outbox.write_audit, None
        )

    return factory
