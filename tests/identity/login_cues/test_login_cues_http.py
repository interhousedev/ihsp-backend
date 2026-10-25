"""Login cue routes: admin role required, masked admin list, no EMIS login publicly."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_users.login_cues import ROUTERS as ADMIN_ROUTERS
from app.interfaces.http.v1.id_registration import ROUTERS as PUBLIC_ROUTERS
from app.modules.identity.application.login_cues import LoginCueService
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter
from tests.conftest import HttpClientFactory
from tests.fakes.clock import FixedClock
from tests.fakes.identity.login_cues import (
    FakeCueGroups,
    InMemoryLoginCueRepository,
    StubStart,
)
from tests.fakes.identity.vault import InMemoryCredentialStore

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient

LOGIN = "20249988771"
GROUP = new_id()


@pytest.fixture
def service(redis: FakeRedis) -> LoginCueService:
    return LoginCueService(
        repository=InMemoryLoginCueRepository(),
        store=InMemoryCredentialStore(),
        groups=FakeCueGroups({GROUP: "10-A"}),
        start=ProfileStart(),
        rate_limiter=RateLimiter(redis),
        clock=FixedClock(datetime(2026, 10, 25, 9, tzinfo=UTC)),
    )


class ProfileStart(StubStart):
    """Answers like StartRegistration: a token, the profile and the login."""

    async def execute(self, **kwargs: object) -> object:
        await super().execute(**kwargs)
        profile = SimpleNamespace(
            first_name="Ali", last_name="Valiyev", middle_name=None, group_name="10-A"
        )
        return SimpleNamespace(
            registration_token="token-" + "x" * 12,
            profile=profile,
            login="ali.valiyev",
            imported_match=None,
        )


async def _client(
    http_client: HttpClientFactory, service: LoginCueService, roles: frozenset[Role]
) -> AsyncClient:
    async def current_actor() -> Actor:
        return Actor(user_id=new_id(), roles=roles)

    return await http_client(
        ADMIN_ROUTERS + PUBLIC_ROUTERS,
        {get_actor: current_actor},
        identity=SimpleNamespace(emis=SimpleNamespace(login_cues=service)),
    )


async def test_admin_routes_need_admin_role(
    http_client: HttpClientFactory, service: LoginCueService
) -> None:
    student = await _client(http_client, service, frozenset({Role.STUDENT}))
    response = await student.get("/v1/admin/login-cues")
    assert response.status_code == 403


async def test_admin_create_and_list_mask_the_login(
    http_client: HttpClientFactory, service: LoginCueService
) -> None:
    admin = await _client(http_client, service, frozenset({Role.ADMIN}))
    created = await admin.post(
        "/v1/admin/login-cues",
        json={
            "emis_login": LOGIN,
            "full_name": "Valiyev Ali Akramovich",
            "group_id": str(GROUP),
        },
    )
    assert created.status_code == 201
    assert LOGIN not in created.text
    assert created.json()["login_masked"] == "••••" + LOGIN[-2:]

    listed = await admin.get("/v1/admin/login-cues")
    assert listed.status_code == 200
    assert LOGIN not in listed.text


async def test_public_routes_never_contain_the_login(
    http_client: HttpClientFactory, service: LoginCueService
) -> None:
    admin = await _client(http_client, service, frozenset({Role.ADMIN}))
    await admin.post(
        "/v1/admin/login-cues/bulk",
        json={
            "items": [
                {
                    "emis_login": LOGIN,
                    "full_name": "Valiyev Ali Akramovich",
                    "group_id": str(GROUP),
                }
            ]
        },
    )
    public = await _client(http_client, service, frozenset())

    groups = await public.get("/v1/id/login-cues/groups")
    assert groups.status_code == 200
    assert LOGIN not in groups.text
    group_id = groups.json()[0]["group_id"]

    cues = await public.get(f"/v1/id/login-cues/groups/{group_id}")
    assert cues.status_code == 200
    assert LOGIN not in cues.text
    assert set(cues.json()[0]) == {"cue_id", "display_name"}
    assert cues.json()[0]["display_name"] == "Ali"


async def test_public_cue_start_with_consumed_cue_is_gone(
    http_client: HttpClientFactory, service: LoginCueService
) -> None:
    admin = await _client(http_client, service, frozenset({Role.ADMIN}))
    created = await admin.post(
        "/v1/admin/login-cues",
        json={"emis_login": LOGIN, "full_name": "Ali", "group_id": str(GROUP)},
    )
    cue_id = created.json()["id"]
    public = await _client(http_client, service, frozenset())
    first = await public.post(
        "/v1/id/register/emis/cue", json={"cue_id": cue_id, "emis_password": "pw"}
    )
    assert first.status_code == 200
    assert LOGIN not in first.text
    assert first.json()["profile"]["login"] == "ali.valiyev"
    second = await public.post(
        "/v1/id/register/emis/cue", json={"cue_id": cue_id, "emis_password": "pw"}
    )
    assert second.status_code == 404
