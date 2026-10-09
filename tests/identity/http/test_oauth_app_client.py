"""GEN-7, PWA-1, PWA-2: the installed app's token handler cookie lasts 90 days."""

from app.modules.identity.domain.client_policy import refresh_days
from tests.identity.http.conftest import Api

from httpx import Response

APP_ORIGIN = "http://localhost:3007"
APP_CLIENT_HEADERS = {"Origin": APP_ORIGIN, "X-IHSP-Client": "web"}
SP_CLIENT_HEADERS = {"Origin": "http://localhost:3002", "X-IHSP-Client": "web"}
NINETY_DAYS = 90 * 24 * 3600
THIRTY_DAYS = 30 * 24 * 3600
TOKEN_BODY = {
    "code": "code-1",
    "code_verifier": "verifier-1",
    "redirect_uri": f"{APP_ORIGIN}/auth/callback/",
}


def refresh_cookie(response: Response) -> str:
    """The one Set-Cookie header of a response."""
    (cookie,) = response.headers.get_list("set-cookie")
    return cookie


def max_age(cookie: str) -> int:
    """The Max-Age attribute of a Set-Cookie header."""
    for part in cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "max-age":
            return int(value)
    raise AssertionError(f"no Max-Age in {cookie}")


async def test_the_app_origin_passes_the_origin_check(api: Api) -> None:
    """PWA-1: app.<domain> is one of the origins the cookie endpoints accept."""
    response = await api.client.post(
        "/v1/oauth/token",
        json={**TOKEN_BODY, "client_id": "app"},
        headers=APP_CLIENT_HEADERS,
    )

    assert response.status_code == 200


async def test_token_exchange_for_app_sets_a_90_day_rt_app_cookie(api: Api) -> None:
    """PWA-2: rt_app lives 90 days, with the same attributes as every refresh cookie."""
    response = await api.client.post(
        "/v1/oauth/token",
        json={**TOKEN_BODY, "client_id": "app"},
        headers=APP_CLIENT_HEADERS,
    )

    cookie = refresh_cookie(response)
    attributes = {part.strip().lower() for part in cookie.split(";")}
    assert cookie.startswith("rt_app=refresh-1;")
    assert {"httponly", "samesite=strict", "path=/v1/oauth"} <= attributes
    assert max_age(cookie) == NINETY_DAYS == 7776000
    assert max_age(cookie) == refresh_days("app") * 24 * 3600
    assert "refresh-1" not in response.text


async def test_token_exchange_for_sp_keeps_the_30_day_cookie(api: Api) -> None:
    """PWA-2: the websites are unchanged."""
    response = await api.client.post(
        "/v1/oauth/token",
        json={**TOKEN_BODY, "client_id": "sp"},
        headers=SP_CLIENT_HEADERS,
    )

    cookie = refresh_cookie(response)
    assert cookie.startswith("rt_sp=refresh-1;")
    assert max_age(cookie) == THIRTY_DAYS == 2592000


async def test_refresh_rotation_for_app_keeps_90_days(api: Api) -> None:
    """PWA-2: the rotated rt_app cookie is renewed for another 90 days."""
    api.world.hydra.tokens = api.world.hydra.tokens.__class__(
        access_token="access.jwt.token", expires_in=600, refresh_token="refresh-2"
    )

    response = await api.client.post(
        "/v1/oauth/refresh",
        json={"client_id": "app"},
        headers={**APP_CLIENT_HEADERS, "Cookie": "rt_app=refresh-1"},
    )

    assert response.status_code == 200
    assert api.world.hydra.last("refresh")["refresh_token"] == "refresh-1"
    cookie = refresh_cookie(response)
    assert cookie.startswith("rt_app=refresh-2;")
    assert max_age(cookie) == NINETY_DAYS


async def test_the_app_cookie_is_not_read_for_another_client(api: Api) -> None:
    """GEN-7: rt_app belongs to `app`; `sp` still needs its own rt_sp."""
    response = await api.client.post(
        "/v1/oauth/refresh",
        json={"client_id": "sp"},
        headers={**SP_CLIENT_HEADERS, "Cookie": "rt_app=refresh-1"},
    )

    assert response.status_code == 401


async def test_logout_of_app_clears_rt_app(api: Api) -> None:
    """PWA-1: signing out of the installed app removes its own cookie."""
    response = await api.client.post(
        "/v1/oauth/logout",
        json={"client_id": "app"},
        headers={**APP_CLIENT_HEADERS, "Cookie": "rt_app=refresh-1"},
    )

    assert response.status_code == 200
    assert api.world.hydra.last("revoke_token")["token"] == "refresh-1"
    cookie = refresh_cookie(response)
    assert cookie.startswith('rt_app="";') or cookie.startswith("rt_app=;")
    assert "max-age=0" in cookie.lower()
