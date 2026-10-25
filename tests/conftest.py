"""Shared fixtures: settings, database, redis, clock, kicker, S3, actors, HTTP client.

The dev compose stack must be running (`docker compose -f
materials/docker-compose.dev.yaml up -d --wait`): PostgreSQL gets a fresh database per
test session and the S3 server a fresh bucket. Redis is fakeredis.
"""

import os
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import uuid4

from app.bootstrap.container import Container
from app.interfaces.http.main import create_app
from app.settings import Settings
from app.shared.actor import Actor
from app.shared.db.engine import make_engine, make_sessionmaker
from app.shared.db.testing import create_database, create_tables, drop_database
from app.shared.i18n.core import I18nCore
from app.shared.paths import LOCALES_DIR
from app.shared.rate_limit import RateLimiter
from tests.factories import make_actor as build_actor
from tests.fakes.clock import FixedClock
from tests.fakes.tasks import FakeTaskKicker

import pytest
import pytest_asyncio
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

# Processes started by tests (taskiq broker) use the in-memory broker.
os.environ.setdefault("IHSP_ENV", "test")

TEST_DB_NAME = f"ihsp_test_{uuid4().hex[:8]}"

S3_CONFIG = AioConfig(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    request_checksum_calculation="when_required",
    response_checksum_validation="when_required",
    connect_timeout=5,
    retries={"max_attempts": 3, "mode": "standard"},
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Settings for tests: the dev compose services, database `ihsp_test_<uuid8>`.

    The database is created by the `engine` fixture; building settings touches nothing.
    """
    base = Settings(env="test")
    url = (
        make_url(base.database.url)
        .set(database=TEST_DB_NAME)
        .render_as_string(hide_password=False)
    )
    database = base.database.model_copy(update={"url": url})
    return base.model_copy(update={"database": database})


@pytest.fixture(scope="session")
def i18n() -> I18nCore:
    """Translations from locales."""
    return I18nCore(LOCALES_DIR).load()


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Engine on a fresh database with every schema and table; dropped at the end."""
    url = settings.database.url
    await create_database(url)
    engine = make_engine(url, pool_size=5)
    try:
        await create_tables(engine)
        yield engine
    finally:
        await engine.dispose()
        await drop_database(url)


@pytest_asyncio.fixture
async def db_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """One connection inside an outer transaction that is rolled back after the test."""
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            yield connection
        finally:
            await outer.rollback()


@pytest_asyncio.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session whose commits only release a SAVEPOINT of the outer transaction."""
    session = AsyncSession(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
def sessionmaker_in_tx(
    db_connection: AsyncConnection,
) -> async_sessionmaker[AsyncSession]:
    """A sessionmaker on the same outer connection, for SQL unit-of-work tests."""
    return async_sessionmaker(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[FakeRedis]:
    """A fresh fakeredis (decode_responses=True, like production)."""
    client = FakeRedis(server=FakeServer(), decode_responses=True)
    await client.flushall()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def clock() -> FixedClock:
    """2026-10-06 09:00 UTC; move it with clock.advance(hours=1)."""
    return FixedClock()


@pytest.fixture
def kicker() -> FakeTaskKicker:
    """Records every task the code under test starts."""
    return FakeTaskKicker()


@pytest_asyncio.fixture(scope="session")
async def s3_bucket(settings: Settings) -> AsyncIterator[str]:
    """A fresh bucket `test-<uuid8>` on the compose S3 server; deleted at the end."""
    bucket = f"test-{uuid4().hex[:8]}"
    async with get_session().create_client(
        "s3",
        endpoint_url=settings.s3.endpoint_url,
        aws_access_key_id=settings.s3.access_key,
        aws_secret_access_key=settings.s3.secret_key.get_secret_value(),
        region_name=settings.s3.region,
        config=S3_CONFIG,
    ) as s3:
        await s3.create_bucket(Bucket=bucket)
        try:
            yield bucket
        finally:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket):
                keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if keys:
                    await s3.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            await s3.delete_bucket(Bucket=bucket)


@pytest.fixture
def make_actor() -> Callable[..., Actor]:
    """Factory: make_actor(Role.TEACHER, user_id=None, **Actor fields) -> Actor."""
    return build_actor


class HttpClientFactory(Protocol):
    """Builds an app with the given routers and returns a client for it."""

    async def __call__(
        self,
        routers: Sequence[APIRouter],
        overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
        **container_fields: Any,
    ) -> AsyncClient:
        """Create the client; container_fields replace Container attributes."""
        ...


@pytest_asyncio.fixture
async def http_client(
    settings: Settings,
    i18n: I18nCore,
    redis: FakeRedis,
    clock: FixedClock,
    kicker: FakeTaskKicker,
) -> AsyncIterator[HttpClientFactory]:
    """Factory `await http_client(routers, overrides, identity=..., sessionmaker=...)`.

    The container has the fake clock, fakeredis and the fake kicker; its engine is lazy
    (connects only when used). `overrides` fill app.dependency_overrides.
    """
    clients: list[AsyncClient] = []
    engines: list[AsyncEngine] = []

    async def factory(
        routers: Sequence[APIRouter],
        overrides: Mapping[Callable[..., Any], Callable[..., Any]] | None = None,
        **container_fields: Any,
    ) -> AsyncClient:
        engine = make_engine(settings.database.url, pool_size=1)
        engines.append(engine)
        container = Container(
            settings=settings,
            clock=clock,
            redis=redis,
            engine=engine,
            sessionmaker=make_sessionmaker(engine),
            kicker=kicker,
            rate_limiter=RateLimiter(redis),
            i18n=i18n,
        )
        for name, value in container_fields.items():
            setattr(container, name, value)
        app = create_app(container, routers=routers)
        if overrides:
            app.dependency_overrides.update(overrides)
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    try:
        yield factory
    finally:
        for client in clients:
            await client.aclose()
        for engine in engines:
            await engine.dispose()
