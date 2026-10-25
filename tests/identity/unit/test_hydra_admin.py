"""The Hydra HTTP client sends the requests Hydra's admin and public APIs expect."""

import json

from app.modules.identity.domain.errors import (
    ChallengeUsedError,
    HydraUnavailableError,
    InvalidChallengeError,
)
from app.modules.identity.infrastructure.hydra.admin import HydraAdmin
from app.shared.base_error import UnauthorizedError

import httpx
import pytest
import respx

ADMIN = "http://hydra-admin:4445"
PUBLIC = "http://hydra-public:4444"


@pytest.fixture
def hydra() -> HydraAdmin:
    """A client with a dummy miniapp secret."""
    return HydraAdmin(
        admin_url=ADMIN,
        public_url=PUBLIC,
        miniapp_client_id="miniapp",
        miniapp_client_secret="s3cret",
    )


@respx.mock
async def test_login_request_is_parsed(hydra: HydraAdmin) -> None:
    """hydra.md 5.1: skip, subject, client, requested scopes and session id."""
    route = respx.get(f"{ADMIN}/admin/oauth2/auth/requests/login").mock(
        return_value=httpx.Response(
            200,
            json={
                "challenge": "lc",
                "skip": True,
                "subject": "u-1",
                "client": {
                    "client_id": "admin",
                    "client_name": "",
                    "metadata": {"a": 1},
                },
                "request_url": "https://hydra/oauth2/auth?x",
                "requested_scope": ["openid"],
                "requested_access_token_audience": [],
                "session_id": "sid-1",
            },
        )
    )

    request = await hydra.get_login_request("lc")

    assert route.calls[0].request.url.params["login_challenge"] == "lc"
    assert (request.skip, request.subject, request.session_id) == (True, "u-1", "sid-1")
    assert request.client.client_id == "admin"
    assert request.client.client_name == "admin"  # falls back to the id
    assert request.client.metadata == {"a": 1}


@respx.mock
async def test_used_challenge_becomes_a_410_with_the_restart_url(
    hydra: HydraAdmin,
) -> None:
    """hydra.md 5.1: 410 carries the URL that restarts the flow."""
    respx.get(f"{ADMIN}/admin/oauth2/auth/requests/consent").mock(
        return_value=httpx.Response(410, json={"redirect_to": "https://hydra/restart"})
    )

    with pytest.raises(ChallengeUsedError) as caught:
        await hydra.get_consent_request("cc")

    assert caught.value.status == 410
    assert caught.value.params == {"redirect_to": "https://hydra/restart"}


@respx.mock
async def test_unknown_challenge_is_a_404(hydra: HydraAdmin) -> None:
    """A made-up challenge is a client error, not a Hydra outage."""
    respx.get(f"{ADMIN}/admin/oauth2/auth/requests/logout").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )

    with pytest.raises(InvalidChallengeError):
        await hydra.get_logout_request("lo")


@respx.mock
async def test_accept_login_sends_subject_amr_and_context(hydra: HydraAdmin) -> None:
    """hydra.md 5.2: the body of the accept call."""
    route = respx.put(f"{ADMIN}/admin/oauth2/auth/requests/login/accept").mock(
        return_value=httpx.Response(200, json={"redirect_to": "https://hydra/next"})
    )

    redirect = await hydra.accept_login(
        "lc",
        subject="u-1",
        remember=True,
        remember_for=2592000,
        amr=["pwd", "otp"],
        context={"session_id": "s-1"},
    )

    assert redirect == "https://hydra/next"
    assert json.loads(route.calls[0].request.content) == {
        "subject": "u-1",
        "remember": True,
        "remember_for": 2592000,
        "amr": ["pwd", "otp"],
        "context": {"session_id": "s-1"},
    }


@respx.mock
async def test_accept_consent_sends_the_claims_in_the_session(
    hydra: HydraAdmin,
) -> None:
    """hydra.md 6.2: access token claims go to session.access_token."""
    route = respx.put(f"{ADMIN}/admin/oauth2/auth/requests/consent/accept").mock(
        return_value=httpx.Response(200, json={"redirect_to": "https://hydra/code"})
    )

    await hydra.accept_consent(
        "cc",
        grant_scope=["openid"],
        grant_audience=["ihsp-api"],
        remember=False,
        access_token_claims={"auth_epoch": 1},
        id_token_claims={"roles": ["student"]},
    )

    body = json.loads(route.calls[0].request.content)
    assert body["grant_scope"] == ["openid"]
    assert body["grant_access_token_audience"] == ["ihsp-api"]
    assert body["session"] == {
        "access_token": {"auth_epoch": 1},
        "id_token": {"roles": ["student"]},
    }


@respx.mock
async def test_revoking_sessions_uses_subject_or_sid_and_tolerates_404(
    hydra: HydraAdmin,
) -> None:
    """hydra.md 8: login sessions by sid; consent sessions by subject and all=true."""
    login = respx.delete(f"{ADMIN}/admin/oauth2/auth/sessions/login").mock(
        return_value=httpx.Response(204)
    )
    consent = respx.delete(f"{ADMIN}/admin/oauth2/auth/sessions/consent").mock(
        return_value=httpx.Response(404)
    )

    await hydra.revoke_login_sessions(sid="sid-1")
    await hydra.revoke_consent_sessions("u-1")
    await hydra.revoke_consent_sessions("u-1", "mcp-client")

    assert dict(login.calls[0].request.url.params) == {"sid": "sid-1"}
    assert dict(consent.calls[0].request.url.params) == {
        "subject": "u-1",
        "all": "true",
    }
    assert dict(consent.calls[1].request.url.params) == {
        "subject": "u-1",
        "client": "mcp-client",
    }


@respx.mock
async def test_code_exchange_is_a_form_post_with_pkce(hydra: HydraAdmin) -> None:
    """hydra.md 9.3: client_id, code, redirect_uri and code_verifier."""
    route = respx.post(f"{PUBLIC}/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 600,
                "token_type": "bearer",
                "scope": "openid",
            },
        )
    )

    tokens = await hydra.exchange_code("sp", "code", "verifier", "https://sp/cb")

    form = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert form == {
        "grant_type": "authorization_code",
        "client_id": "sp",
        "code": "code",
        "code_verifier": "verifier",
        "redirect_uri": "https://sp/cb",
    }
    assert (tokens.access_token, tokens.refresh_token, tokens.expires_in) == (
        "at",
        "rt",
        600,
    )


@respx.mock
async def test_rejected_code_is_unauthorized(hydra: HydraAdmin) -> None:
    """An invalid_grant answer becomes a 401, not a Hydra outage."""
    respx.post(f"{PUBLIC}/oauth2/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    with pytest.raises(UnauthorizedError):
        await hydra.exchange_code("sp", "bad", "v", "https://sp/cb")


@respx.mock
async def test_jwt_bearer_authenticates_as_the_miniapp_client(
    hydra: HydraAdmin,
) -> None:
    """hydra.md 11.2: assertion, scope and audience with basic client auth."""
    route = respx.post(f"{PUBLIC}/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 600})
    )

    await hydra.jwt_bearer("a.b.c", "openid offline_access", "ihsp-api")

    request = route.calls[0].request
    assert request.headers["authorization"].startswith("Basic ")
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert form["assertion"] == "a.b.c"
    assert form["audience"] == "ihsp-api"


@respx.mock
async def test_client_metadata_is_replaced_with_a_json_patch(hydra: HydraAdmin) -> None:
    """hydra.md 9.4: PATCH with a JSON Patch document."""
    route = respx.patch(f"{ADMIN}/admin/clients/mcp-1").mock(
        return_value=httpx.Response(
            200, json={"client_id": "mcp-1", "metadata": {"verified": True}}
        )
    )

    client = await hydra.set_client_metadata("mcp-1", {"verified": True})

    assert json.loads(route.calls[0].request.content) == [
        {"op": "add", "path": "/metadata", "value": {"verified": True}}
    ]
    assert client.metadata == {"verified": True}


@respx.mock
async def test_unreachable_hydra_is_a_503(hydra: HydraAdmin) -> None:
    """A network error or 5xx is HydraUnavailableError."""
    respx.get(f"{ADMIN}/admin/clients").mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(HydraUnavailableError) as caught:
        await hydra.list_clients()

    assert caught.value.status == 503


@respx.mock
async def test_clients_are_listed_and_fetched(hydra: HydraAdmin) -> None:
    """hydra.md 9.4: GET /admin/clients and /admin/clients/{id}."""
    respx.get(f"{ADMIN}/admin/clients").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "client_id": "a",
                    "client_name": "A",
                    "redirect_uris": ["https://a/cb"],
                },
                {"client_id": "b"},
            ],
        )
    )
    respx.get(f"{ADMIN}/admin/clients/a").mock(
        return_value=httpx.Response(200, json={"client_id": "a", "client_name": "A"})
    )
    respx.get(f"{ADMIN}/admin/clients/zzz").mock(return_value=httpx.Response(404))

    listed = await hydra.list_clients()

    assert [c.client_id for c in listed] == ["a", "b"]
    assert listed[0].redirect_uris == ("https://a/cb",)
    assert (await hydra.get_client("a")).client_name == "A"
    assert await hydra.get_client("zzz") is None


@respx.mock
async def test_logout_reject_and_introspection_calls(hydra: HydraAdmin) -> None:
    """hydra.md 6.3, 8.3."""
    respx.put(f"{ADMIN}/admin/oauth2/auth/requests/logout/accept").mock(
        return_value=httpx.Response(200, json={"redirect_to": "https://hydra/bye"})
    )
    respx.put(f"{ADMIN}/admin/oauth2/auth/requests/login/reject").mock(
        return_value=httpx.Response(200, json={"redirect_to": "https://hydra/rejected"})
    )
    respx.put(f"{ADMIN}/admin/oauth2/auth/requests/consent/reject").mock(
        return_value=httpx.Response(200, json={"redirect_to": "https://hydra/denied"})
    )
    respx.post(f"{ADMIN}/admin/oauth2/introspect").mock(
        return_value=httpx.Response(200, json={"active": True, "ext": {"sid": "s"}})
    )
    respx.post(f"{PUBLIC}/oauth2/revoke").mock(return_value=httpx.Response(200))
    respx.get(f"{ADMIN}/admin/oauth2/auth/requests/logout").mock(
        return_value=httpx.Response(200, json={"subject": "u", "sid": "sid-1"})
    )

    assert await hydra.accept_logout("lo") == "https://hydra/bye"
    assert (
        await hydra.reject_login("lc", "login_required", "x")
        == "https://hydra/rejected"
    )
    assert (
        await hydra.reject_consent("cc", "access_denied", "x") == "https://hydra/denied"
    )
    assert (await hydra.introspect("tok"))["ext"] == {"sid": "s"}
    await hydra.revoke_token("sp", "tok")
    request = await hydra.get_logout_request("lo")
    assert (request.subject, request.sid) == ("u", "sid-1")


@respx.mock
async def test_hydra_5xx_on_the_token_endpoint_is_a_503(hydra: HydraAdmin) -> None:
    """A Hydra outage is not the user's fault."""
    respx.post(f"{PUBLIC}/oauth2/token").mock(return_value=httpx.Response(502))

    with pytest.raises(HydraUnavailableError):
        await hydra.refresh("sp", "rt")


@respx.mock
async def test_setting_metadata_of_an_unknown_client_is_a_404(
    hydra: HydraAdmin,
) -> None:
    """Verifying a client that disappeared."""
    respx.patch(f"{ADMIN}/admin/clients/gone").mock(return_value=httpx.Response(404))

    with pytest.raises(InvalidChallengeError):
        await hydra.set_client_metadata("gone", {"verified": True})
