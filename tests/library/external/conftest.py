"""Fixtures of the UniLibrary tests: settings, the mocked source, the built stack."""

from collections.abc import AsyncIterator, Iterator
from dataclasses import replace

from app.modules.library.infrastructure.unilibrary.factory import (
    UniLibraryStack,
    build_unilibrary,
)
from app.modules.library.wiring import LibraryServices
from app.modules.library.wiring_core import LibraryCore
from app.modules.library.wiring_external import ExternalServices, build_external
from app.settings import LibrarySettings
from tests.fakes.clock import FixedClock
from tests.fakes.library.external_catalog import FakeExternalCatalog

import pytest
import respx
from fakeredis.aioredis import FakeRedis

BASE = "https://api.unilibrary.uz"
LIST_PATH = "/api/user/guest-publisher-resources-with-media"
DETAIL_PATH = "/api/user/guest-publisher-resources"


class Sleeper:
    """A `sleep` that moves the fixed clock instead of waiting."""

    def __init__(self, clock: FixedClock) -> None:
        """Remember the clock and start with no sleeps."""
        self.clock = clock
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        """Record the wait and jump the clock forward by it."""
        self.slept.append(seconds)
        self.clock.advance(seconds=seconds)


@pytest.fixture
def ext_settings() -> LibrarySettings:
    """UniLibrary on, a generous request budget (the budget has its own tests)."""
    return LibrarySettings(
        unilibrary_enabled=True,
        unilibrary_contact="library@ihsu.uz",
        unilibrary_rps=1000.0,
    )


@pytest.fixture
def sleeper(clock: FixedClock) -> Sleeper:
    """Waits that advance the test clock."""
    return Sleeper(clock)


@pytest.fixture
def upstream() -> Iterator[respx.MockRouter]:
    """The UniLibrary API; no request leaves the process."""
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def stack(
    ext_settings: LibrarySettings,
    redis: FakeRedis,
    clock: FixedClock,
    sleeper: Sleeper,
    upstream: respx.MockRouter,
) -> AsyncIterator[UniLibraryStack]:
    """The real client, cache, breaker and catalog over fakeredis and respx."""
    built = build_unilibrary(ext_settings, redis, clock, sleep=sleeper)
    yield built
    await built.aclose()


# - - - The external area over fakes (use case, repository and HTTP tests) - - -


@pytest.fixture
def catalog() -> FakeExternalCatalog:
    """UniLibrary as a scripted in-memory catalogue."""
    return FakeExternalCatalog()


@pytest.fixture
def ext_core(library: LibraryServices, ext_settings: LibrarySettings) -> LibraryCore:
    """The library core with UniLibrary switched on in the environment."""
    return replace(library.core, settings=ext_settings)


@pytest.fixture
def external(ext_core: LibraryCore, catalog: FakeExternalCatalog) -> ExternalServices:
    """The external area with the fake catalogue (enabled)."""
    return build_external(ext_core, catalog=catalog)


@pytest.fixture
def external_off(
    library: LibraryServices, catalog: FakeExternalCatalog
) -> ExternalServices:
    """The external area with the environment defaults: UniLibrary is off."""
    core = replace(library.core, settings=LibrarySettings())
    return build_external(core, catalog=catalog)
