"""HTTP fixtures: the learning routers on a test app with a switchable caller."""

from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.lms_learning import ROUTERS
from app.modules.lms.wiring_learning import LearningServices
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient


@pytest.fixture
def caller() -> dict[str, Actor]:
    """The actor the next request is made as: `caller["actor"] = teacher`."""
    return {}


@pytest.fixture
async def client(
    http_client: HttpClientFactory,
    learning: LearningServices,
    caller: dict[str, Actor],
) -> AsyncClient:
    """A client for the learning routes whose authentication is overridden."""
    client: AsyncClient = await http_client(
        ROUTERS,
        {get_actor: lambda: caller["actor"]},
        lms=SimpleNamespace(learning=learning),
    )
    return client


@pytest.fixture
async def anonymous_client(
    http_client: HttpClientFactory,
    learning: LearningServices,
) -> AsyncClient:
    """A client for the learning routes with the real authentication."""
    client: AsyncClient = await http_client(
        ROUTERS, None, lms=SimpleNamespace(learning=learning)
    )
    return client
