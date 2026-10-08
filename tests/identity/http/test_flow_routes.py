"""ID-16: Hydra's login, consent and logout URLs are plain redirects."""

from app.modules.identity.ports.hydra_gateway import LogoutRequest
from tests.identity.http.conftest import Api

ID_URL = "http://localhost:3001"


async def test_login_without_a_session_redirects_to_the_form(api: Api) -> None:
    """The static login app opens only when a form is needed."""
    api.world.hydra.add_login("lc-1")

    response = await api.client.get(
        "/v1/oauth/flow/login", params={"login_challenge": "lc-1"}
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith(
        f"{ID_URL}/login/?login_challenge=lc-1&client_id=sp"
    )
    assert response.headers["cache-control"] == "no-store"


async def test_login_with_a_session_redirects_straight_back_to_hydra(api: Api) -> None:
    """SSO: no page between the two Hydra requests."""
    user = await api.world.add_user()
    api.world.add_session(user, hydra_sid="sid-1")
    api.world.hydra.add_login(
        "lc-1", skip=True, subject=str(user.id), session_id="sid-1"
    )

    response = await api.client.get(
        "/v1/oauth/flow/login", params={"login_challenge": "lc-1"}
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://hydra/continue?login_verifier=lc-1"


async def test_consent_of_a_first_party_client_redirects_straight_back(
    api: Api,
) -> None:
    """Our apps never see a consent page."""
    user = await api.world.add_user()
    session = api.world.add_session(user)
    api.world.hydra.add_consent(
        "cc-1",
        client_id="lms",
        subject=str(user.id),
        requested_scope=("openid",),
        context={"session_id": str(session.id)},
    )

    response = await api.client.get(
        "/v1/oauth/flow/consent", params={"consent_challenge": "cc-1"}
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://hydra/code?consent_verifier=cc-1"


async def test_consent_of_a_third_party_client_redirects_to_the_page(api: Api) -> None:
    """MCP connectors are asked."""
    user = await api.world.add_user()
    api.world.hydra.add_consent("cc-1", client_id="claude", subject=str(user.id))

    response = await api.client.get(
        "/v1/oauth/flow/consent", params={"consent_challenge": "cc-1"}
    )

    assert response.headers["location"] == f"{ID_URL}/consent/?consent_challenge=cc-1"


async def test_logout_redirects_to_hydra(api: Api) -> None:
    """The logout page of the id app is not shown."""
    api.world.hydra.logout_requests["lo-1"] = LogoutRequest(
        challenge="lo-1", subject=None, sid=None
    )

    response = await api.client.get(
        "/v1/oauth/flow/logout", params={"logout_challenge": "lo-1"}
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://hydra/after-logout"


async def test_a_missing_challenge_is_a_validation_error(api: Api) -> None:
    """Hydra always sends one; anything else is a bad request."""
    response = await api.client.get("/v1/oauth/flow/login")

    assert response.status_code == 422
