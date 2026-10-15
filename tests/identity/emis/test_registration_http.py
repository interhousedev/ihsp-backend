"""Routes of task B2: statuses, bodies and error types of the API contract."""

from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.id_registration import ROUTERS
from app.shared.actor import Actor, Role
from tests.conftest import HttpClientFactory
from tests.identity.emis.world import NEW_PASSWORD, World

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

USE_CASES = (
    "register_start",
    "register_email_code",
    "register_complete",
    "reclaim_start",
    "reclaim_email_code",
    "reclaim_complete",
    "update_emis_password",
    "delete_account",
)


class Api:
    """A client over the B2 routers with a switchable caller."""

    def __init__(self, client: AsyncClient, actor: dict[str, Actor | None]) -> None:
        self.client = client
        self._actor = actor

    def login_as(self, user_id: UUID, *roles: Role) -> None:
        self._actor["current"] = Actor(
            user_id=user_id, roles=frozenset(roles or {Role.STUDENT})
        )


@pytest.fixture
async def api(world: World, http_client: HttpClientFactory) -> Api:
    holder: dict[str, Actor | None] = {"current": None}

    async def current_actor() -> Actor:
        actor = holder["current"]
        assert actor is not None, "the test did not log in"
        return actor

    emis = SimpleNamespace(**{name: getattr(world, name) for name in USE_CASES})
    client = await http_client(
        ROUTERS,
        {get_actor: current_actor},
        identity=SimpleNamespace(emis=emis),
    )
    return Api(client, holder)


async def post(api: Api, path: str, body: dict[str, Any], **headers: str) -> Any:
    return await api.client.post(path, json=body, headers=headers)


# - - - Registration - - -


async def test_register_emis_returns_the_registration_start(api: Api) -> None:
    """ID-1: 200 with RegistrationStart."""
    response = await post(
        api,
        "/v1/id/register/emis",
        {"emis_login": "student01", "emis_password": "password"},
    )

    body = response.json()
    assert response.status_code == 200
    assert len(body["registration_token"]) >= 40
    assert body["profile"] == {
        "first_name": "Alisher",
        "last_name": "Abdullayev",
        "middle_name": "Alisherovich",
        "group_name": "2TN2",
        "login": "abdullayev.alisher",
    }
    assert body["imported_match"] is None


async def test_register_email_is_accepted_and_uses_the_accept_language(
    api: Api, world: World
) -> None:
    """ID-4: 202 without a body; the mail follows Accept-Language."""
    start = await post(
        api,
        "/v1/id/register/emis",
        {"emis_login": "student01", "emis_password": "password"},
        **{"accept-language": "uz-UZ,ru;q=0.8"},
    )

    response = await post(
        api,
        "/v1/id/register/email",
        {
            "registration_token": start.json()["registration_token"],
            "email": "a@example.com",
        },
    )

    assert response.status_code == 202
    assert response.content == b""
    assert world.emails.sent[-1][3] == "uz"


async def test_register_complete_returns_login_and_redirect(
    api: Api, world: World
) -> None:
    """ID-4, ID-5: the whole flow over HTTP."""
    start = await post(
        api,
        "/v1/id/register/emis",
        {"emis_login": "student01", "emis_password": "password"},
    )
    token = start.json()["registration_token"]
    await post(
        api,
        "/v1/id/register/email",
        {"registration_token": token, "email": "a@example.com"},
    )

    response = await post(
        api,
        "/v1/id/register/complete",
        {
            "registration_token": token,
            "password": NEW_PASSWORD,
            "email_code": world.emails.last_code(),
            "login_challenge": "challenge-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "login": "abdullayev.alisher",
        "redirect_to": "https://hydra.test/continue?c=challenge-1",
        "login_ticket": None,
    }


@pytest.mark.parametrize(
    ("body", "status", "error_type"),
    [
        ({"emis_login": "student01", "emis_password": "bad"}, 401, "emis/auth-failed"),
        ({"emis_login": "down", "emis_password": "password"}, 503, "emis/unavailable"),
        ({"emis_login": "", "emis_password": "x"}, 422, "common/request-validation"),
    ],
)
async def test_register_emis_error_types(
    api: Api, body: dict[str, str], status: int, error_type: str
) -> None:
    """ID-1: the web translates these problem types."""
    response = await post(api, "/v1/id/register/emis", body)

    assert response.status_code == status
    assert response.json()["type"] == error_type
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_the_registration_rate_limit_is_a_429_with_retry_after(
    api: Api,
) -> None:
    """ID-3: "Too many attempts, try again later"."""
    for _ in range(10):
        await post(
            api,
            "/v1/id/register/emis",
            {"emis_login": "student01", "emis_password": "x"},
        )

    response = await post(
        api,
        "/v1/id/register/emis",
        {"emis_login": "student01", "emis_password": "password"},
    )

    assert response.status_code == 429
    assert response.json()["type"] == "common/rate-limited"
    assert response.json()["params"]["retry_after"] >= 1


async def test_an_invalid_email_is_a_validation_error(api: Api) -> None:
    """ID-4: the email is validated by the schema."""
    response = await post(
        api,
        "/v1/id/register/email",
        {"registration_token": "x" * 30, "email": "not-an-email"},
    )

    assert response.status_code == 422
    assert response.json()["type"] == "common/request-validation"


async def test_an_expired_registration_is_a_410(api: Api) -> None:
    """ID-1: id/registration-expired."""
    response = await post(
        api,
        "/v1/id/register/complete",
        {"registration_token": "x" * 30, "password": NEW_PASSWORD, "email_code": "1"},
    )

    assert response.status_code == 410
    assert response.json()["type"] == "id/registration-expired"


async def test_a_long_hydra_login_challenge_passes_validation(api: Api) -> None:
    """Log in -> Register: Hydra v2+ challenges are encrypted flows over 1 KB."""
    response = await post(
        api,
        "/v1/id/register/complete",
        {
            "registration_token": "x" * 30,
            "password": NEW_PASSWORD,
            "email_code": "123456",
            "login_challenge": "c" * 2400,
        },
    )

    assert response.status_code == 410
    assert response.json()["type"] == "id/registration-expired"


async def test_a_weak_password_lists_the_broken_rules(api: Api, world: World) -> None:
    """ID-4: the form shows which rules failed."""
    start = await post(
        api,
        "/v1/id/register/emis",
        {"emis_login": "student01", "emis_password": "password"},
    )
    token = start.json()["registration_token"]
    await post(
        api,
        "/v1/id/register/email",
        {"registration_token": token, "email": "a@example.com"},
    )

    response = await post(
        api,
        "/v1/id/register/complete",
        {"registration_token": token, "password": "alllowercase", "email_code": "1"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "id/password-weak"
    assert body["params"]["errors"] == ["id-password-no-digit", "id-password-no-upper"]


# - - - Reclaim - - -


async def test_reclaim_flow_over_http(api: Api, world: World) -> None:
    """ID-28: 200 with the token, 202 for the code, 204 at the end."""
    await world.register()
    start = await post(
        api,
        "/v1/id/reclaim/emis",
        {"emis_login": "student01", "emis_password": "password"},
    )
    assert start.status_code == 200
    assert start.json()["login"] == "abdullayev.alisher"
    token = start.json()["reclaim_token"]

    email = await post(
        api, "/v1/id/reclaim/email", {"reclaim_token": token, "email": "n@example.com"}
    )
    done = await post(
        api,
        "/v1/id/reclaim/complete",
        {
            "reclaim_token": token,
            "new_password": "NewPass456",
            "email_code": world.emails.last_code(),
        },
    )

    assert (email.status_code, done.status_code) == (202, 204)
    assert done.content == b""


async def test_reclaim_of_an_unknown_profile_is_a_404(api: Api) -> None:
    """UF-ID-15: id/user-not-found."""
    response = await post(
        api,
        "/v1/id/reclaim/emis",
        {"emis_login": "student01", "emis_password": "password"},
    )

    assert response.status_code == 404
    assert response.json()["type"] == "id/user-not-found"


# - - - Account: EMIS password and deletion - - -


async def test_update_emis_password_returns_the_status(api: Api, world: World) -> None:
    """ID-8: ``{emis_status}`` for a student."""
    _, registered = await world.register()
    api.login_as(registered.user_id)

    response = await post(api, "/v1/id/me/emis-password", {"emis_password": "password"})

    assert response.status_code == 200
    assert response.json() == {"emis_status": "active"}


async def test_update_emis_password_is_for_students_only(api: Api) -> None:
    """ID-8: teachers get 403."""
    api.login_as(UUID(int=5), Role.TEACHER)

    response = await post(api, "/v1/id/me/emis-password", {"emis_password": "password"})

    assert response.status_code == 403
    assert response.json()["type"] == "common/forbidden"


async def test_delete_account_returns_202_with_the_closing_date(
    api: Api, world: World
) -> None:
    """ID-29: 202 ``{closes_on}``."""
    _, registered = await world.register()
    api.login_as(registered.user_id)

    response = await api.client.request(
        "DELETE", "/v1/id/me", json={"password": NEW_PASSWORD}
    )

    assert response.status_code == 202
    assert response.json() == {"closes_on": "2026-11-05"}


async def test_delete_account_with_a_wrong_password_is_a_403(
    api: Api, world: World
) -> None:
    """ID-29: not a 401, which would log the web client out."""
    _, registered = await world.register()
    api.login_as(registered.user_id)

    response = await api.client.request(
        "DELETE", "/v1/id/me", json={"password": "Wrong123"}
    )

    assert response.status_code == 403
    assert response.json()["type"] == "id/wrong-password"


async def test_delete_account_needs_authentication(
    http_client: HttpClientFactory, world: World
) -> None:
    """ID-29: bearer token required (identity is not wired in this client)."""
    client = await http_client(ROUTERS)

    response = await client.request("DELETE", "/v1/id/me", json={"password": "x"})

    assert response.status_code == 401
    assert response.json()["type"] == "auth/unauthorized"


def test_every_route_of_the_contract_exists() -> None:
    """API contract: paths and methods of task B2, and a valid OpenAPI schema."""
    app = FastAPI()
    for router in ROUTERS:
        app.include_router(router)

    schema = app.openapi()["paths"]

    assert {(m.upper(), p) for p, item in schema.items() for m in item} == {
        ("POST", "/v1/id/register/emis"),
        ("POST", "/v1/id/register/email"),
        ("POST", "/v1/id/register/complete"),
        ("POST", "/v1/id/reclaim/emis"),
        ("POST", "/v1/id/reclaim/email"),
        ("POST", "/v1/id/reclaim/complete"),
        ("POST", "/v1/id/me/emis-password"),
        ("DELETE", "/v1/id/me"),
    }
