"""HTTP fixtures: the catalogue routers on the fake-backed module."""

from collections.abc import Awaitable, Callable

from app.interfaces.http.dependencies import get_actor, get_optional_actor
from app.interfaces.http.public.library import ROUTERS as PUBLIC_ROUTERS
from app.interfaces.http.v1.library.catalogue import ROUTERS as CATALOGUE_ROUTERS
from app.modules.library.wiring import LibraryServices
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory

import pytest
from httpx import AsyncClient

ROUTERS = [*CATALOGUE_ROUTERS, *PUBLIC_ROUTERS]


@pytest.fixture
def api(
    http_client: HttpClientFactory, library: LibraryServices
) -> Callable[..., Awaitable[AsyncClient]]:
    """`await api(actor)` is a client signed in as the actor (None: a visitor)."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides: dict[Callable[..., object], Callable[..., object]] = {
            get_optional_actor: lambda: actor
        }
        if actor is not None:
            overrides[get_actor] = lambda: actor
        return await http_client(ROUTERS, overrides, library=library)

    return build
