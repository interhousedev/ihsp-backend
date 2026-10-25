"""ID-16, MCP-2, MCP-3: consent for first-party and MCP clients."""

from datetime import timedelta
from uuid import UUID

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    AdminServerForbiddenError,
    ConnectorInvalidError,
    RoleMissingError,
    SecondFactorRequiredError,
)
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from tests.fakes.identity.hydra import client
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")
MCP_URL = (
    "https://hydra/oauth2/auth?resource=https://api/mcp/{server}"
    "&redirect_uri=https://claude.example/cb"
)


async def mcp_consent(
    world: World,
    user_id: UUID,
    server: str = "student",
    *,
    client_id: str = "mcp-client",
    mfa_hours_ago: float | None = None,
    scopes: tuple[str, ...] = ("openid", "schedule:read", "marks:read"),
) -> str:
    """Register a consent request of an MCP client."""
    mfa = (
        (world.clock.now() - timedelta(hours=mfa_hours_ago)).isoformat()
        if mfa_hours_ago is not None
        else None
    )
    world.hydra.add_consent(
        "cc-1",
        client_id=client_id,
        subject=str(user_id),
        request_url=MCP_URL.format(server=server),
        requested_scope=scopes,
        context={"session_id": "x", "amr": ["pwd", "otp"], "mfa_at": mfa},
    )
    return "cc-1"


async def test_first_party_client_is_accepted_with_the_session_claims(
    auth_world: World,
) -> None:
    """ID-16: no screen; claims carry epoch, roles, amr, mfa_at and sid."""
    user = await auth_world.add_user(roles={Role.STUDENT, Role.TEACHER}, auth_epoch=4)
    session = auth_world.add_session(
        user, amr=["pwd", "otp"], mfa_at=auth_world.clock.now()
    )
    auth_world.hydra.add_consent(
        "cc-1",
        client_id="sp",
        subject=str(user.id),
        requested_scope=("openid", "offline_access"),
        context={"session_id": str(session.id)},
    )

    info = await auth_world.auth.get_consent_info.execute("cc-1")

    assert info.redirect_to == "https://hydra/code?consent_verifier=cc-1"
    accepted = auth_world.hydra.last("accept_consent")
    assert accepted["grant_audience"] == ["ihsp-api"]
    assert accepted["grant_scope"] == ["openid", "offline_access"]
    assert accepted["access_token_claims"] == {
        "auth_epoch": 4,
        "roles": ["student", "teacher"],
        "amr": ["pwd", "otp"],
        "mfa_at": auth_world.clock.now().isoformat(),
        "sid": str(session.id),
    }
    assert accepted["id_token_claims"] == {"roles": ["student", "teacher"]}


async def test_consent_is_rejected_when_the_session_was_revoked(
    auth_world: World,
) -> None:
    """GEN-5: a revoked session gets no tokens."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user)
    session.revoked_at = auth_world.clock.now()
    auth_world.hydra.add_consent(
        "cc-1",
        client_id="sp",
        subject=str(user.id),
        context={"session_id": str(session.id)},
    )

    info = await auth_world.auth.get_consent_info.execute("cc-1")

    assert info.redirect_to == "https://hydra/denied?challenge=cc-1"
    assert "accept_consent" not in auth_world.hydra.names()


async def test_mcp_client_sees_a_screen_with_server_scopes_and_domain(
    auth_world: World,
) -> None:
    """MCP-3: client name, unverified flag, redirect domain, server and scopes."""
    user = await auth_world.add_user()
    challenge = await mcp_consent(auth_world, user.id)

    info = await auth_world.auth.get_consent_info.execute(challenge)

    assert info.redirect_to is None
    assert info.server == "student"
    assert info.verified is False
    assert info.redirect_domain == "claude.example"
    assert info.requested_scopes == ["schedule:read", "marks:read"]
    assert info.requires_otp is False


async def test_mcp_client_asking_for_nothing_gets_all_scopes_of_the_server(
    auth_world: World,
) -> None:
    """The user can untick scopes, so the screen lists every scope of the server."""
    user = await auth_world.add_user()
    challenge = await mcp_consent(auth_world, user.id, scopes=("openid",))

    info = await auth_world.auth.get_consent_info.execute(challenge)

    assert "flashcards:write" in info.requested_scopes
    assert len(info.requested_scopes) == 8


async def test_student_cannot_consent_to_the_admin_server(auth_world: World) -> None:
    """MCP-1: only Administration may connect to the admin server."""
    user = await auth_world.add_user()
    auth_world.hydra.clients["trusted"] = client("trusted", verified=True)
    challenge = await mcp_consent(auth_world, user.id, "admin", client_id="trusted")

    with pytest.raises(RoleMissingError):
        await auth_world.auth.get_consent_info.execute(challenge)


async def test_dynamic_client_cannot_ask_for_the_admin_server(
    auth_world: World,
) -> None:
    """MCP-3: only verified clients reach the Administration server."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    challenge = await mcp_consent(auth_world, admin.id, "admin")

    with pytest.raises(AdminServerForbiddenError):
        await auth_world.auth.get_consent_info.execute(challenge)


async def test_admin_consent_without_an_otp_code_is_refused(auth_world: World) -> None:
    """MCP-3: the Administration server needs a step-up code."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    auth_world.hydra.clients["trusted"] = client(
        "trusted", verified=True, dynamic=False
    )
    challenge = await mcp_consent(
        auth_world, admin.id, "admin", client_id="trusted", mfa_hours_ago=1
    )

    with pytest.raises(SecondFactorRequiredError):
        await auth_world.auth.accept_consent.execute(
            challenge, accept=True, grant_scopes=["people:read"], otp_code=None, ctx=CTX
        )

    assert auth_world.store.connectors == {}


async def test_admin_consent_with_an_old_login_is_refused(auth_world: World) -> None:
    """MCP-3: password + OTP login within 12 hours is required."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    auth_world.hydra.clients["trusted"] = client(
        "trusted", verified=True, dynamic=False
    )
    challenge = await mcp_consent(
        auth_world, admin.id, "admin", client_id="trusted", mfa_hours_ago=13
    )

    with pytest.raises(SecondFactorRequiredError):
        await auth_world.auth.accept_consent.execute(
            challenge,
            accept=True,
            grant_scopes=["people:read"],
            otp_code="123456",
            ctx=CTX,
        )


async def test_admin_consent_with_the_step_up_code_creates_a_30_day_connector(
    auth_world: World,
) -> None:
    """MCP-3: after the code the connector exists and Hydra gets mcp-admin tokens."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    auth_world.hydra.clients["trusted"] = client(
        "trusted", verified=True, dynamic=False
    )
    challenge = await mcp_consent(
        auth_world, admin.id, "admin", client_id="trusted", mfa_hours_ago=1
    )
    await auth_world.auth.send_consent_otp.execute(challenge, CTX)
    code = auth_world.otp.last("step-up").code

    redirect = await auth_world.auth.accept_consent.execute(
        challenge,
        accept=True,
        grant_scopes=["people:read", "audit:read"],
        otp_code=code,
        ctx=CTX,
    )

    assert redirect == "https://hydra/code?consent_verifier=cc-1"
    (connector,) = auth_world.store.connectors.values()
    assert connector.server == "admin"
    assert connector.kind == "oauth"
    assert connector.hydra_client_id == "trusted"
    assert connector.expires_at == auth_world.clock.now() + timedelta(days=30)
    accepted = auth_world.hydra.last("accept_consent")
    assert accepted["grant_audience"] == ["mcp-admin"]
    assert accepted["access_token_claims"]["connector_id"] == str(connector.id)
    assert accepted["access_token_claims"]["sid"] == str(connector.id)
    assert "connector.created" in auth_world.store.audit_types(admin.id)


async def test_consent_otp_goes_to_the_subject_of_the_challenge_and_is_limited(
    auth_world: World,
) -> None:
    """The consent page has no bearer token: the challenge names the user."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    auth_world.hydra.clients["trusted"] = client(
        "trusted", verified=True, dynamic=False
    )
    challenge = await mcp_consent(auth_world, admin.id, "admin", client_id="trusted")

    channels = await auth_world.auth.send_consent_otp.execute(challenge, CTX)

    assert channels == ["email"]
    sent = auth_world.otp.last("step-up")
    assert sent.user_id == admin.id
    with pytest.raises(RateLimitedError):
        await auth_world.auth.send_consent_otp.execute(challenge, CTX)


async def test_student_consent_creates_a_connector_with_the_chosen_scopes(
    auth_world: World,
) -> None:
    """MCP-3: the result appears as a connector; the user can untick scopes."""
    user = await auth_world.add_user()
    challenge = await mcp_consent(auth_world, user.id)

    await auth_world.auth.accept_consent.execute(
        challenge, accept=True, grant_scopes=["schedule:read"], otp_code=None, ctx=CTX
    )

    (connector,) = auth_world.store.connectors.values()
    assert connector.scopes == ["schedule:read"]
    assert connector.expires_at == auth_world.clock.now() + timedelta(days=365)
    accepted = auth_world.hydra.last("accept_consent")
    assert accepted["grant_scope"] == ["openid", "schedule:read"]
    assert accepted["grant_audience"] == ["mcp-student"]


async def test_scopes_outside_the_request_are_refused(auth_world: World) -> None:
    """MCP-3: a client cannot be granted scopes it did not ask for."""
    user = await auth_world.add_user()
    challenge = await mcp_consent(auth_world, user.id, scopes=("openid", "marks:read"))

    with pytest.raises(ConnectorInvalidError):
        await auth_world.auth.accept_consent.execute(
            challenge,
            accept=True,
            grant_scopes=["flashcards:write"],
            otp_code=None,
            ctx=CTX,
        )


async def test_denying_rejects_the_consent_and_creates_nothing(
    auth_world: World,
) -> None:
    """UF-MCP-02 4a: the client gets an error, no connector is created."""
    user = await auth_world.add_user()
    challenge = await mcp_consent(auth_world, user.id)

    redirect = await auth_world.auth.accept_consent.execute(
        challenge, accept=False, grant_scopes=[], otp_code=None, ctx=CTX
    )

    assert redirect == "https://hydra/denied?challenge=cc-1"
    assert auth_world.store.connectors == {}
