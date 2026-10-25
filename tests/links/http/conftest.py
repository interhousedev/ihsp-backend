"""HTTP fixtures: the links routers on the fake-backed module."""

from collections.abc import Awaitable, Callable

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.public.robots import ROUTERS as ROBOTS_ROUTERS
from app.interfaces.http.public.rooms import ROUTERS as ROOM_ROUTERS
from app.interfaces.http.public.short_links import (
    HOST_ROUTERS,
)
from app.interfaces.http.public.short_links import ROUTERS as SHORT_ROUTERS
from app.interfaces.http.v1.admin_moderation import ROUTERS as MODERATION_ROUTERS
from app.interfaces.http.v1.links import ROUTERS as LINK_ROUTERS
from app.shared.actor import Actor
from tests.conftest import HttpClientFactory
from tests.fakes.links.world import LinksWorld

import pytest
from httpx import AsyncClient

ALL_ROUTERS = [
    *LINK_ROUTERS,
    *MODERATION_ROUTERS,
    *SHORT_ROUTERS,
    *ROOM_ROUTERS,
    *ROBOTS_ROUTERS,
]


@pytest.fixture
def api(
    http_client: HttpClientFactory, world: LinksWorld
) -> Callable[..., Awaitable[AsyncClient]]:
    """`await api(actor)` returns a client logged in as the actor (or anonymous)."""

    async def build(actor: Actor | None = None) -> AsyncClient:
        overrides = {get_actor: (lambda: actor)} if actor else None
        return await http_client(ALL_ROUTERS, overrides, links=world.services)

    return build


@pytest.fixture
def host_api(
    http_client: HttpClientFactory, world: LinksWorld
) -> Callable[[], Awaitable[AsyncClient]]:
    """A client for the short link host routes (`/{slug}` without /s)."""

    async def build() -> AsyncClient:
        return await http_client(HOST_ROUTERS, None, links=world.services)

    return build
