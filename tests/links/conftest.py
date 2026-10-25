"""Fixtures of the links tests: a wired module on fakes with real Redis semantics."""

from collections.abc import AsyncIterator

from app.settings import Settings
from app.shared.db.engine import make_engine, make_sessionmaker
from app.shared.i18n.core import I18nCore
from tests.fakes.clock import FixedClock
from tests.fakes.links.world import LinksWorld, build_world

import pytest_asyncio
from fakeredis.aioredis import FakeRedis


@pytest_asyncio.fixture
async def world(
    settings: Settings, clock: FixedClock, redis: FakeRedis, i18n: I18nCore
) -> AsyncIterator[LinksWorld]:
    """The links module on in-memory fakes; the database engine is never used."""
    engine = make_engine(settings.database.url, pool_size=1)
    try:
        yield build_world(
            settings=settings,
            clock=clock,
            redis=redis,
            i18n=i18n,
            sessionmaker=make_sessionmaker(engine),
        )
    finally:
        await engine.dispose()
