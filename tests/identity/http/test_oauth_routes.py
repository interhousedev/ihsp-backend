"""GEN-7, ID-16: /v1/oauth/* token handler and Hydra token hook."""

from typing import Any
from uuid import UUID

from app.settings import DEV_SERVICE_TOKEN
from tests.identity.http.conftest import APP_HEADERS, Api
from tests.identity.support import sign_init_data

from httpx import Response

JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
TOKEN_BODY = {
    "client_id": "sp",
    "code": "code-1",
    "code_verifier": "verifier-1",
    "redirect_uri": "https://sp.example/cb",
}


def set_cookies(response: Response) -> list[str]:
    """The Set-Cookie headers of a response."""
    return response.headers.get_list("set-cookie")


async def test_token_exchange_sets_the_refresh_cookie_with_the_exact_attributes(
    api: Api,
) -> None:
    """GEN-7: HttpOnly, SameSite=Lax, Path=/v1/oauth, host-only, 30 days."""
    response = await api.client.post(
        "/v1/oauth/token", json=TOKEN_BODY, headers=APP_HEADERS
    )

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "access.jwt.token",
        "token_type": "Bearer",
        "expires_in": 600,
    }
    (cookie,) = set_cookies(response)
    attributes = {part.strip().lower() for part in cookie.split(";")}
    assert cookie.startswith("rt_sp=refresh-1;")
    assert {
        "httponly",
        "samesite=lax",
        "path=/v1/oauth",
        "max-age=2592000",
    } <= attributes
    assert "secure" not in attributes  # TOKENS__REFRESH_COOKIE_SECURE is off in dev
    assert not any(part.startswith("domain=") for part in attributes)
    assert "refresh-1" not in response.text


async def test_cookie_endpoints_need_the_client_header_and_an_allowed_origin(
    api: Api,
) -> None:
    """Contract: X-IHSP-Client plus an Origin of one of our apps."""
    for headers in (
        {},
        {"Origin": "http://localhost:3002"},
        {"X-IHSP-Client": "web"},
        {"Origin": "https://evil.example", "X-IHSP-Client": "web"},
    ):
        response = await api.client.post(
            "/v1/oauth/token", json=TOKEN_BODY, headers=headers
        )
        assert response.status_code == 403
        assert response.headers["content-type"] == "application/problem+json"

    refresh = await api.client.post("/v1/oauth/refresh", json={"client_id": "sp"})
    assert refresh.status_code == 403


async def test_unknown_client_cannot_use_the_token_handler(api: Api) -> None:
    """The cookie name comes from the client id."""
    response = await api.client.post(
        "/v1/oauth/token", json={**TOKEN_BODY, "client_id": "evil"}, headers=APP_HEADERS
    )

    assert response.status_code == 422
    assert response.json()["type"] == "id/unknown-client"


async def test_refresh_rotates_the_cookie(api: Api) -> None:
    """GEN-7: the new refresh token replaces the old cookie."""
    api.world.hydra.tokens = api.world.hydra.tokens.__class__(
        access_token="access.jwt.token", expires_in=600, refresh_token="refresh-2"
    )

    response = await api.client.post(
        "/v1/oauth/refresh",
        json={"client_id": "sp"},
        headers={**APP_HEADERS, "Cookie": "rt_sp=refresh-1"},
    )

    assert response.status_code == 200
    assert api.world.hydra.last("refresh")["refresh_token"] == "refresh-1"
    (cookie,) = set_cookies(response)
    assert cookie.startswith("rt_sp=refresh-2;")


async def test_refresh_without_a_cookie_clears_it_and_answers_401(api: Api) -> None:
    """Contract: invalid refresh token -> cookie cleared, 401."""
    response = await api.client.post(
        "/v1/oauth/refresh", json={"client_id": "sp"}, headers=APP_HEADERS
    )

    assert response.status_code == 401
    assert response.json()["type"] == "auth/unauthorized"
    (cookie,) = set_cookies(response)
    assert cookie.startswith('rt_sp="";') or cookie.startswith("rt_sp=;")
    assert "max-age=0" in cookie.lower()


async def test_refresh_rejected_by_hydra_clears_the_cookie(api: Api) -> None:
    """A revoked or reused refresh token is a 401 with a cleared cookie."""
    from app.shared.base_error import UnauthorizedError

    async def refuse(client_id: str, refresh_token: str):
        raise UnauthorizedError()

    api.world.hydra.refresh = refuse  # type: ignore[method-assign]

    response = await api.client.post(
        "/v1/oauth/refresh",
        json={"client_id": "sp"},
        headers={**APP_HEADERS, "Cookie": "rt_sp=stale"},
    )

    assert response.status_code == 401
    assert "max-age=0" in set_cookies(response)[0].lower()


async def test_logout_revokes_clears_the_cookie_and_returns_the_hydra_url(
    api: Api,
) -> None:
    """Contract: {logout_url}; the cookie is cleared, the refresh token revoked."""
    response = await api.client.post(
        "/v1/oauth/logout",
        json={"client_id": "sp"},
        headers={**APP_HEADERS, "Cookie": "rt_sp=refresh-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "logout_url": "http://localhost:4444/oauth2/sessions/logout"
    }
    assert api.world.hydra.last("revoke_token")["token"] == "refresh-1"
    assert "max-age=0" in set_cookies(response)[0].lower()


async def test_telegram_token_exchange_returns_a_token_without_a_cookie(
    api: Api,
) -> None:
    """ID-19: the mini app gets an access token only."""
    user = await api.world.add_user()
    api.world.add_link(user, 555)
    init_data = sign_init_data(auth_date=int(api.world.clock.now().timestamp()))

    response = await api.client.post(
        "/v1/oauth/telegram", json={"client_id": "sp", "init_data": init_data}
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "tg.access.token"
    assert set_cookies(response) == []


async def test_telegram_token_exchange_with_bad_init_data_is_401(api: Api) -> None:
    """ID-20: invalid initData."""
    response = await api.client.post(
        "/v1/oauth/telegram",
        json={"client_id": "sp", "init_data": "hash=x&auth_date=1"},
    )

    assert response.status_code == 401


# - - - Token hook - - -

HOOK_HEADERS = {"Authorization": f"Bearer {DEV_SERVICE_TOKEN}"}


def hook_body(user_id: UUID, extra: dict[str, Any]) -> dict[str, Any]:
    """What Hydra posts."""
    return {
        "session": {
            "id_token": {
                "subject": str(user_id),
                "id_token_claims": {"sub": str(user_id)},
            },
            "extra": extra,
        },
        "request": {"client_id": "sp", "grant_types": ["authorization_code"]},
    }


async def test_hook_needs_the_service_token(api: Api) -> None:
    """Contract: the hook is authorised with the service token."""
    user = await api.world.add_user()

    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic x"},
    ):
        response = await api.client.post(
            "/v1/oauth/token-hook", json=hook_body(user.id, {}), headers=headers
        )
        assert response.status_code == 401


async def test_hook_answers_200_with_the_full_claims(api: Api) -> None:
    """hydra.md 4: a 200 replaces the extras, so all claims are sent."""
    user = await api.world.add_user(auth_epoch=3)
    session = api.world.add_session(user)

    response = await api.client.post(
        "/v1/oauth/token-hook",
        json=hook_body(user.id, {"sid": str(session.id), "amr": ["pwd"]}),
        headers=HOOK_HEADERS,
    )

    assert response.status_code == 200
    claims = response.json()["session"]["access_token"]
    assert claims["auth_epoch"] == 3 and claims["sid"] == str(session.id)
    assert claims["roles"] == ["student"]
    assert response.json()["session"]["id_token"] == {"roles": ["student"]}


async def test_hook_denies_a_blocked_user_with_403(api: Api) -> None:
    """GEN-5: Hydra turns the 403 into access_denied."""
    from app.shared.contracts.identity import UserStatus

    user = await api.world.add_user(status=UserStatus.BLOCKED)

    response = await api.client.post(
        "/v1/oauth/token-hook", json=hook_body(user.id, {}), headers=HOOK_HEADERS
    )

    assert response.status_code == 403


async def test_hook_leaves_subjectless_requests_unchanged_with_204(api: Api) -> None:
    """hydra.md 4: 204 keeps the token as is."""
    response = await api.client.post(
        "/v1/oauth/token-hook",
        json={"session": {"id_token": {}, "extra": {}}, "request": {}},
        headers=HOOK_HEADERS,
    )

    assert response.status_code == 204
    assert response.content == b""


async def test_hook_with_a_non_ascii_token_is_401_not_500(api: Api) -> None:
    """Review 2026-10-11: compare_digest on text raised TypeError for non-ASCII."""
    user = await api.world.add_user()

    response = await api.client.post(
        "/v1/oauth/token-hook",
        json=hook_body(user.id, {}),
        headers={b"Authorization": "Bearer t\u00f6ken".encode("latin-1")},
    )

    assert response.status_code == 401
