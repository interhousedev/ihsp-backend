"""HTTP fixtures for activities routes (mirror tests/links/http/conftest.py).

The implementation must provide:
  app.interfaces.http.v1.activities.ROUTERS       (student/club side)
  app.interfaces.http.v1.admin_activities.ROUTERS (/v1/admin/activities/...)
  app.interfaces.http.public.clubs.ROUTERS        (/v1/public/clubs..., events)
  and `activities=` as the dependency key wired to ActivitiesServices.
"""

from collections.abc import Awaitable, Callable

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.public.clubs import ROUTERS as PUBLIC_ROUTERS
from app.interfaces.http.v1.activities import ROUTERS as STUDENT_ROUTERS
from app.interfaces.http.v1.admin_activities import ROUTERS as ADMIN_ROUTERS
from app.shared.actor import Actor, Role
from tests.conftest import HttpClientFactory
from tests.fakes.activities.world import ActivitiesWorld, build_world

import pytest
from httpx import AsyncClient

MakeClient = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
def world() -> ActivitiesWorld:
    return build_world()


@pytest.fixture
def make_client(world: ActivitiesWorld, http_client: HttpClientFactory) -> MakeClient:
    async def _make(actor: Actor | None = None) -> AsyncClient:
        overrides = {get_actor: (lambda: actor)} if actor is not None else {}
        return await http_client(
            [*STUDENT_ROUTERS, *ADMIN_ROUTERS, *PUBLIC_ROUTERS],
            overrides,
            activities=world.services,
        )

    return _make


@pytest.fixture
def su(world: ActivitiesWorld) -> Actor:
    return world.add_staff(Role.SU)


@pytest.fixture
def student(world: ActivitiesWorld) -> Actor:
    return world.add_student()
