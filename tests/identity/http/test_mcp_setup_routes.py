"""MCP-3: the setup data, the registration route and a user's own clients."""

import asyncio
from typing import Any

from tests.identity.http.conftest import Api

import pytest

SETUP = "/v1/id/me/mcp-setup"
CLIENTS = "/v1/id/me/mcp-clients"
REGISTER = "/v1/oauth/mcp/register"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"


async def test_setup_and_clients_need_a_bearer_token(api: Api) -> None:
    """Contract: bearer auth."""
    assert (await api.client.get(f"{SETUP}/claude")).status_code == 401
    assert (await api.client.get(CLIENTS)).status_code == 401


@pytest.mark.parametrize("service", ["chatgpt", "gemini", "claude", "custom"])
async def test_setup_of_every_service(api: Api, service: str) -> None:
    """MCP-3: the server URL, the modes and the OAuth settings, no secret."""
    api.login_as(await api.world.add_user())

    response = await api.client.get(f"{SETUP}/{service}", params={"server": "student"})

    assert response.status_code == 200
    body = response.json()
    assert body["server_url"].endswith("/student")
    assert "oauth_dcr" in body["auth_modes"]
    assert body["oauth"]["registration_endpoint"].endswith(REGISTER)
    assert body["oauth"]["audience"] == "mcp-student"
    assert body["oauth"]["resource"] == body["server_url"]
    assert body["oauth"]["code_challenge_method"] == "S256"
    assert "schedule:read" in body["oauth"]["scopes"]
    assert "secret" not in response.text.replace("client_secret_", "")
    has_token = service in {"claude", "custom"}
    assert (body["token_route"] == "/v1/id/me/connectors") is has_token
    assert ("static_token" in body["auth_modes"]) is has_token


async def test_setup_refuses_a_server_the_role_may_not_use(api: Api) -> None:
    """MCP-3: a student has no admin server."""
    api.login_as(await api.world.add_user())
    response = await api.client.get(f"{SETUP}/custom", params={"server": "admin"})
    assert response.status_code == 403


async def test_setup_refuses_an_unknown_service(api: Api) -> None:
    """Contract: the service is a closed list."""
    api.login_as(await api.world.add_user())
    assert (await api.client.get(f"{SETUP}/grok")).status_code == 422


async def test_registration_is_public_and_follows_rfc_7591(api: Api) -> None:
    """MCP-3: the fields clients read; a public client has no secret."""
    response = await api.client.post(
        REGISTER,
        json={
            "redirect_uris": [CLAUDE],
            "token_endpoint_auth_method": "none",
            "jwks_uri": "http://hydra:4445/admin",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["client_id"] and body["client_name"] == "Claude"
    assert body["token_endpoint_auth_method"] == "none"
    assert body["grant_types"] == ["authorization_code", "refresh_token"]
    assert "client_secret" not in body
    assert "jwks_uri" not in body


async def test_registration_without_a_method_gets_a_secret(api: Api) -> None:
    """RFC 7591: the default method is client_secret_basic."""
    response = await api.client.post(REGISTER, json={"redirect_uris": [CLAUDE]})
    body = response.json()
    assert body["token_endpoint_auth_method"] == "client_secret_basic"
    assert body["client_secret"]
    assert body["client_secret_expires_at"] == 0


async def test_registration_refuses_with_the_rfc_error_shape(api: Api) -> None:
    """RFC 7591 section 3.2.2."""
    response = await api.client.post(
        REGISTER, json={"redirect_uris": ["https://evil.example/cb"]}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_own_client_secret_is_shown_once(api: Api) -> None:
    """MCP-3: create, list without the secret, delete, gone."""
    api.login_as(await api.world.add_user())

    created = await api.client.post(
        CLIENTS,
        json={
            "service": "gemini",
            "server": "student",
            "redirect_uri": "https://vertexaisearch.cloud.google.com/oauth-redirect",
        },
    )
    assert created.status_code == 201
    secret = created.json()["client_secret"]
    client_id = created.json()["client"]["client_id"]
    assert created.json()["client"]["server"] == "student"

    listed = await api.client.get(CLIENTS)
    assert [c["client_id"] for c in listed.json()] == [client_id]
    assert secret not in listed.text

    assert (await api.client.delete(f"{CLIENTS}/{client_id}")).status_code == 204
    assert (await api.client.get(CLIENTS)).json() == []
    assert (await api.client.delete(f"{CLIENTS}/{client_id}")).status_code == 404


PROVISION = "/v1/id/me/mcp-setup"


@pytest.mark.parametrize("service", ["chatgpt", "gemini", "claude"])
async def test_provision_creates_one_client_and_repeats_without_a_secret(
    api: Api, service: str
) -> None:
    """MCP-5: 'Yes' pre-creates the OAuth client once; a repeat has no new secret."""
    api.login_as(await api.world.add_user())

    first = await api.client.post(
        f"{PROVISION}/{service}", params={"server": "student"}
    )
    assert first.status_code == 200
    body = first.json()
    assert body["created"] is True
    assert body["client_secret"]
    assert body["client"]["service"] == service
    assert body["client"]["server"] == "student"

    second = await api.client.post(
        f"{PROVISION}/{service}", params={"server": "student"}
    )
    assert second.status_code == 200
    again = second.json()
    assert again["created"] is False
    assert again["client_secret"] is None
    assert again["client"]["client_id"] == body["client"]["client_id"]

    listed = await api.client.get(CLIENTS)
    assert [c["client_id"] for c in listed.json()] == [body["client"]["client_id"]]
    assert body["client_secret"] not in listed.text
    assert body["client_secret"] not in second.text


async def test_concurrent_provisions_create_one_client(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP-5 race: two 'Yes' clicks at once create one client, not two."""
    api.login_as(await api.world.add_user())
    hydra = api.world.hydra
    create = hydra.create_client

    async def slow_create(**kwargs: Any) -> Any:
        # Hydra is a network call; the second request must find the lock taken.
        await asyncio.sleep(0.2)
        return await create(**kwargs)

    monkeypatch.setattr(hydra, "create_client", slow_create)

    first, second = await asyncio.gather(
        api.client.post(f"{PROVISION}/claude", params={"server": "student"}),
        api.client.post(f"{PROVISION}/claude", params={"server": "student"}),
    )
    assert first.status_code == 200 and second.status_code == 200
    bodies = [first.json(), second.json()]
    assert sorted(b["created"] for b in bodies) == [False, True]
    assert bodies[0]["client"]["client_id"] == bodies[1]["client"]["client_id"]
    assert len((await api.client.get(CLIENTS)).json()) == 1


async def test_setup_read_creates_no_client(api: Api) -> None:
    """MCP-5: a GET only reads; the clients appear after a provision."""
    api.login_as(await api.world.add_user())

    assert (
        await api.client.get(f"{SETUP}/chatgpt", params={"server": "student"})
    ).status_code == 200
    assert (await api.client.get(CLIENTS)).json() == []


async def test_provision_refuses_custom_and_a_server_the_role_may_not_use(
    api: Api,
) -> None:
    """MCP-5: custom needs the user's own redirect, so it is never pre-created."""
    api.login_as(await api.world.add_user())

    custom = await api.client.post(f"{PROVISION}/custom", params={"server": "student"})
    assert custom.status_code == 422
    admin = await api.client.post(f"{PROVISION}/claude", params={"server": "admin"})
    assert admin.status_code == 403
    assert (await api.client.get(CLIENTS)).json() == []
