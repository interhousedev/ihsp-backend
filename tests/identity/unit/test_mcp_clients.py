"""MCP-3: redirect allowlist, client registration and resource binding at consent."""

from uuid import UUID

from app.modules.identity.application.consent_support import mcp_server
from app.modules.identity.application.mcp_clients import RegistrationRefusedError
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import ConnectorInvalidError
from app.modules.identity.domain.mcp_clients import (
    is_safe_own_redirect,
    service_of_redirect,
)
from app.modules.identity.ports.hydra_gateway import ConsentRequest, HydraClient
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")
BASE = "https://mcp.ihsu.uz"
USER = "018f0000-0000-7000-8000-000000000001"
OTHER = "018f0000-0000-7000-8000-000000000002"
CLAUDE = "https://claude.ai/api/mcp/auth_callback"


@pytest.mark.parametrize(
    ("uri", "service"),
    [
        (CLAUDE, "claude"),
        ("https://chatgpt.com/connector_platform_oauth_redirect", "chatgpt"),
        ("https://chatgpt.com/connector/oauth/abc_123", "chatgpt"),
        ("https://vertexaisearch.cloud.google.com/oauth-redirect", "gemini"),
        ("https://oauth-redirect.googleusercontent.com/r/my-app", "gemini"),
        ("https://oauth-redirect-test.googleusercontent.com/a/my-app", "gemini"),
    ],
)
def test_known_redirects_map_to_their_service(uri: str, service: str) -> None:
    """MCP-3: the documented redirect URIs of each client."""
    assert service_of_redirect(uri) == service


@pytest.mark.parametrize(
    "uri",
    [
        f"{CLAUDE}/",
        f"{CLAUDE}?x=1",
        "http://claude.ai/api/mcp/auth_callback",
        "https://claude.ai.evil.example/api/mcp/auth_callback",
        "https://chatgpt.com/connector/oauth/a/b",
        "https://chatgpt.com/connector/oauth/a?next=https://evil.example",
        "https://chatgpt.com.evil.example/connector/oauth/a",
        "https://oauth-redirect.googleusercontent.com/x/my-app",
        "https://oauth-redirectXgoogleusercontent.com/r/my-app",
        "https://evil.example/cb",
    ],
)
def test_anything_else_is_not_on_the_allowlist(uri: str) -> None:
    """MCP-3: near misses are refused."""
    assert service_of_redirect(uri) is None


def test_an_operator_can_add_an_exact_uri() -> None:
    """MCP-3: only the exact URI."""
    extra = ("https://client.example/cb",)
    assert service_of_redirect(extra[0], extra=extra) == "custom"
    assert service_of_redirect(f"{extra[0]}/", extra=extra) is None


@pytest.mark.parametrize(
    ("uri", "safe"),
    [
        ("https://client.example/cb", True),
        ("http://127.0.0.1:3334/cb", True),
        ("http://client.example/cb", False),
        ("https://client.example/*", False),
        ("https://user:pw@client.example/cb", False),
        ("https://client.example/cb#frag", False),
        ("javascript:alert(1)", False),
    ],
)
def test_own_client_redirects(uri: str, safe: bool) -> None:
    """MCP-3: a user's own client needs https or loopback."""
    assert is_safe_own_redirect(uri) is safe


async def test_registration_decides_name_scope_and_grants(auth_world: World) -> None:
    """MCP-3: a client cannot look like another or choose its scopes."""
    created = await auth_world.auth.register_mcp_client.execute(
        redirect_uris=[CLAUDE],
        client_name="Totally Official School App",
        auth_method="none",
        ctx=CTX,
    )

    assert created.client.client_name == "Claude"
    assert created.client_secret is None
    recorded = auth_world.hydra.last("create_client")
    assert "schedule:read" in recorded["scope"]
    assert "offline_access" in recorded["scope"]
    assert recorded["auth_method"] == "none"


@pytest.mark.parametrize(
    "uris",
    [
        [],
        ["https://evil.example/cb"],
        [CLAUDE, "https://evil.example/cb"],
        [CLAUDE, "https://chatgpt.com/connector_platform_oauth_redirect"],
    ],
)
async def test_registration_refuses_other_redirects(
    auth_world: World, uris: list[str]
) -> None:
    """MCP-3: every URI must be allowed, and all of one service."""
    with pytest.raises(RegistrationRefusedError) as refused:
        await auth_world.auth.register_mcp_client.execute(
            redirect_uris=uris, client_name=None, auth_method="none", ctx=CTX
        )
    assert refused.value.error == "invalid_redirect_uri"
    assert "create_client" not in auth_world.hydra.names()


async def test_registration_refuses_other_auth_methods(auth_world: World) -> None:
    """MCP-3: private_key_jwt would make Hydra fetch a client-given URL."""
    with pytest.raises(RegistrationRefusedError) as refused:
        await auth_world.auth.register_mcp_client.execute(
            redirect_uris=[CLAUDE],
            client_name=None,
            auth_method="private_key_jwt",
            ctx=CTX,
        )
    assert refused.value.error == "invalid_client_metadata"


def _consent(
    url: str,
    *,
    subject: str = USER,
    audience: tuple[str, ...] = (),
    metadata: dict[str, str] | None = None,
) -> ConsentRequest:
    return ConsentRequest(
        challenge="cc",
        subject=subject,
        client=HydraClient("c", "c", metadata=metadata or {}),
        request_url=url,
        requested_audience=audience,
    )


AUTH = "https://id.ihsu.uz/oauth2/auth"


def test_resource_must_be_the_exact_url_of_this_deployment() -> None:
    """MCP-3: RFC 8707 binding."""
    good = _consent(f"{AUTH}?resource=https://mcp.ihsu.uz/lms/")
    assert mcp_server(good, BASE) == "lms"
    for bad in (
        "https://evil.example/mcp/student",
        "https://mcp.ihsu.uz.evil.example/student",
        "https://mcp.ihsu.uz/other",
    ):
        with pytest.raises(ConnectorInvalidError):
            # A valid audience does not rescue a wrong resource.
            mcp_server(_consent(f"{AUTH}?resource={bad}", audience=("mcp-lms",)), BASE)


def test_two_different_resources_are_refused() -> None:
    """MCP-3: a token is for one server."""
    url = f"{AUTH}?resource={BASE}/student&resource={BASE}/admin"
    with pytest.raises(ConnectorInvalidError):
        mcp_server(_consent(url), BASE)


def test_audience_and_own_client_name_the_server_without_a_resource() -> None:
    """MCP-3: Gemini Enterprise is not documented to send `resource`."""
    assert mcp_server(_consent(AUTH, audience=("mcp-lms",)), BASE) == "lms"
    own = _consent(AUTH, metadata={"mcp_server": "student", "owner_user_id": USER})
    assert mcp_server(own, BASE) == "student"
    with pytest.raises(ConnectorInvalidError):
        mcp_server(_consent(AUTH), BASE)


def test_own_client_is_for_its_owner_and_its_server() -> None:
    """MCP-3: a custom redirect URI cannot phish another user."""
    metadata = {"mcp_server": "student", "owner_user_id": USER}
    with pytest.raises(ConnectorInvalidError):
        mcp_server(_consent(AUTH, subject=OTHER, metadata=metadata), BASE)
    with pytest.raises(ConnectorInvalidError):
        mcp_server(_consent(f"{AUTH}?resource={BASE}/lms", metadata=metadata), BASE)


@pytest.mark.parametrize("method", ["&code_challenge_method=plain", ""])
def test_pkce_must_be_s256(method: str) -> None:
    """OAuth 2.1: Hydra also accepts plain; an omitted method means plain."""
    url = f"{AUTH}?resource={BASE}/student&code_challenge=x{method}"
    with pytest.raises(ConnectorInvalidError):
        mcp_server(_consent(url), BASE)
    good = f"{AUTH}?resource={BASE}/student&code_challenge=x&code_challenge_method=S256"
    assert mcp_server(_consent(good), BASE) == "student"


def _actor(user: str = USER, *roles: Role) -> Actor:
    return Actor(user_id=UUID(user), roles=frozenset(roles or (Role.STUDENT,)))


async def _own(auth_world: World, actor: Actor) -> str:
    created = await auth_world.auth.mcp_clients.create(
        actor,
        service="custom",
        server="student",
        redirect_uri="https://client.example/cb",
        name=None,
    )
    assert created.client_secret
    return created.client.client_id


async def test_own_clients_are_scoped_to_the_owner(auth_world: World) -> None:
    """MCP-3: IDOR: another user sees nothing and gets 404 on delete."""
    client_id = await _own(auth_world, _actor())

    assert [c.client_id for c in await auth_world.auth.mcp_clients.owned(_actor())] == [
        client_id
    ]
    assert await auth_world.auth.mcp_clients.owned(_actor(OTHER)) == []
    with pytest.raises(NotFoundError):
        await auth_world.auth.mcp_clients.delete(_actor(OTHER), client_id, CTX)
    assert client_id in auth_world.hydra.clients


async def test_own_client_redirect_must_fit_the_service(auth_world: World) -> None:
    """MCP-3: choosing `claude` does not allow another redirect URI."""
    with pytest.raises(ConnectorInvalidError):
        await auth_world.auth.mcp_clients.create(
            _actor(),
            service="claude",
            server="student",
            redirect_uri="https://client.example/cb",
            name=None,
        )


async def test_own_clients_are_capped(auth_world: World) -> None:
    """MCP-3: at most five per user."""
    for _ in range(5):
        await _own(auth_world, _actor())
    with pytest.raises(ConnectorInvalidError):
        await _own(auth_world, _actor())
