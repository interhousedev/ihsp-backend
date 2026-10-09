"""Fixtures of the integration tests: whole containers built over fakes."""

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from app.bootstrap.common import BuildOverrides, build_container
from app.bootstrap.container import Container
from app.bootstrap.seed.students import CapturingEmailSender
from app.settings import Settings
from tests.fakes.clock import FixedClock
from tests.fakes.files.storage import InMemoryStorage
from tests.fakes.identity.vault import InMemoryCredentialStore
from tests.fakes.tasks import FakeTaskKicker

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

SCHEMAS = (
    "id",
    "academic",
    "files",
    "links",
    "ai",
    "notify",
    "admin",
    "mail",
    "lms",
    "notebooks",
    "library",
)

ContainerFactory = Callable[..., Coroutine[Any, Any, Container]]


class _MemoryS3(InMemoryStorage):
    """Stands in for S3Storage: the demo seed writes real file blobs."""

    def __init__(self, **_: object) -> None:
        super().__init__()

    async def close(self) -> None:
        """Nothing to close."""


@pytest.fixture(autouse=True)
def memory_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """No object store runs in the tests: the files module writes to memory."""
    monkeypatch.setattr("app.modules.files.wiring.S3Storage", _MemoryS3)


class IntegrationWorld:
    """The fakes a container is built with, kept for the test to inspect."""

    def __init__(self, clock: FixedClock, kicker: FakeTaskKicker) -> None:
        """Create the credential store and the email capture."""
        self.clock = clock
        self.kicker = kicker
        self.credentials = InMemoryCredentialStore()
        self.email = CapturingEmailSender()


@pytest_asyncio.fixture
async def world(clock: FixedClock, kicker: FakeTaskKicker) -> IntegrationWorld:
    """Clock, kicker, credential store and email capture shared by one test."""
    return IntegrationWorld(clock, kicker)


@pytest_asyncio.fixture
async def make_container(
    settings: Settings,
    engine: AsyncEngine,
    redis: FakeRedis,
    world: IntegrationWorld,
) -> AsyncIterator[ContainerFactory]:
    """`await make_container("all")`: a container of that process over fakes.

    The database is the test database of the session; Redis is fakeredis; the
    clock, the task kicker, Vault and email are the fakes of `world`.
    """
    built: list[Container] = []

    async def factory(process: str, **urls: str) -> Container:
        """Build the container; keyword arguments replace `settings.urls` fields."""
        used = settings.model_copy(
            update={"urls": settings.urls.model_copy(update=urls)}
        )
        container = await build_container(
            used,
            process=process,
            kicker=world.kicker,
            overrides=BuildOverrides(
                clock=world.clock,
                redis=redis,
                credentials=world.credentials,
                email_sender=world.email,
            ),
        )
        built.append(container)
        return container

    try:
        yield factory
    finally:
        for container in built:
            await container.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_database(engine: AsyncEngine) -> AsyncIterator[None]:
    """These tests commit for real (as a process would): empty every table after."""
    yield
    async with engine.begin() as conn:
        tables = await conn.execute(
            text(
                "SELECT quote_ident(schemaname) || '.' || quote_ident(tablename) "
                "FROM pg_tables WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(SCHEMAS)},
        )
        names = ", ".join(row[0] for row in tables)
        if names:
            await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
