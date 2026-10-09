"""ID-16, ID-17: how login sessions are created, reused and revoked."""

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    LoginTakenError,
    OtpInvalidError,
    RoleMissingError,
    UserNotFoundError,
)
from app.modules.identity.domain.scopes import server_from_resource
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


async def test_registration_can_log_the_new_user_in(auth_world: World) -> None:
    """B2 uses LoginAcceptor after creating an account: amr is the caller's choice."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")

    redirect = await auth_world.auth.login_acceptor.accept(
        "lc-1",
        user.id,
        amr=["pwd"],
        ip="203.0.113.5",
        user_agent="Firefox",
        remember=True,
    )

    assert redirect == "https://hydra/continue?login_verifier=lc-1"
    (session,) = auth_world.store.sessions.values()
    assert (session.user_agent, session.amr, session.hydra_sid) == (
        "Firefox",
        ["pwd"],
        "hydra-sid-lc-1",
    )


async def test_login_acceptor_refuses_inactive_users(auth_world: World) -> None:
    """A blocked or unknown user gets no session."""
    user = await auth_world.add_user(status=UserStatus.BLOCKED)
    auth_world.hydra.add_login("lc-1")

    with pytest.raises(UserNotFoundError):
        await auth_world.auth.login_acceptor.accept(
            "lc-1", user.id, amr=["pwd"], ip=None, user_agent=None, remember=False
        )


async def test_missing_ip_is_stored_as_the_unspecified_address(
    auth_world: World,
) -> None:
    """The sessions table needs an inet value even when the proxy sent none."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")

    await auth_world.auth.login_acceptor.accept(
        "lc-1", user.id, amr=["pwd"], ip="not-an-ip", user_agent=None, remember=False
    )

    (session,) = auth_world.store.sessions.values()
    assert (session.ip, session.user_agent) == ("0.0.0.0", "")


async def test_logging_in_again_in_the_same_browser_reuses_the_session(
    auth_world: World,
) -> None:
    """ID-11: the admin 12 hour rule re-authenticates the same Hydra session."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    old = auth_world.add_session(admin, hydra_sid="hydra-sid-lc-1", amr=["pwd"])
    auth_world.hydra.add_login("lc-1", client_id="admin")
    auth_world.clock.advance(hours=13)
    first = await auth_world.auth.log_in_with_password.execute(
        "lc-1", admin.login or "", PASSWORD, remember=True, ctx=CTX
    )
    assert first.second_factor is not None

    await auth_world.auth.log_in_with_otp.execute(
        "lc-1",
        admin.login or "",
        auth_world.otp.last("login2fa").code,
        ticket=first.second_factor.ticket,
        ctx=CTX,
    )

    (session,) = auth_world.store.sessions.values()
    assert session.id == old.id
    assert session.mfa_at == auth_world.clock.now()
    assert session.amr == ["pwd", "otp"]


async def test_hydra_session_of_another_user_does_not_steal_the_row(
    auth_world: World,
) -> None:
    """A shared browser: the second user gets their own session row."""
    first = await auth_world.add_user()
    second = await auth_world.add_user(login="x.y", recovery_email="x@example.org")
    auth_world.add_session(first, hydra_sid="hydra-sid-lc-1")
    auth_world.hydra.add_login("lc-1")

    await auth_world.auth.login_acceptor.accept(
        "lc-1", second.id, amr=["pwd"], ip=None, user_agent=None, remember=False
    )

    assert len(auth_world.store.sessions) == 2
    mine = next(s for s in auth_world.store.sessions.values() if s.user_id == second.id)
    assert mine.hydra_sid is None


async def test_revoke_everything_for_the_account_revoker_port(
    auth_world: World,
) -> None:
    """B2 (reclaim, deletion): epoch bump, sessions, connectors, Telegram links."""
    user = await auth_world.add_user(auth_epoch=1)
    session = auth_world.add_session(user)
    connector = auth_world.add_connector(user)
    auth_world.add_link(user, 555)

    await auth_world.auth.account_revoker.revoke_everything(user.id)

    assert auth_world.user(user.id).auth_epoch == 2
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert auth_world.store.connectors[connector.id].revoked_at is not None
    assert auth_world.store.links == {}
    assert await auth_world.redis.exists(f"auth:revoked:{session.id}")


async def test_revoke_everything_can_keep_the_telegram_links(auth_world: World) -> None:
    """ID-23: a password reset keeps Telegram."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    await auth_world.auth.account_revoker.revoke_everything(user.id, keep_telegram=True)

    assert 555 in auth_world.store.links


async def test_revoke_everything_for_an_unknown_user(auth_world: World) -> None:
    """id/user-not-found."""
    from app.shared.ids import new_id

    with pytest.raises(UserNotFoundError):
        await auth_world.auth.account_revoker.revoke_everything(new_id())


async def test_hydra_outage_does_not_undo_the_revocation(auth_world: World) -> None:
    """Refresh is blocked by the token hook, so a Hydra error is only logged."""
    from app.modules.identity.domain.errors import HydraUnavailableError

    user = await auth_world.add_user()
    session = auth_world.add_session(user)

    async def down(**kwargs: object) -> None:
        raise HydraUnavailableError()

    auth_world.hydra.revoke_login_sessions = down  # type: ignore[method-assign]

    await auth_world.auth.account_revoker.revoke_everything(user.id)

    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert await auth_world.redis.exists(f"auth:revoked:{session.id}")


async def test_second_factor_ticket_is_bound_to_its_challenge_and_login(
    auth_world: World,
) -> None:
    """A ticket cannot be replayed for another login or challenge."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    other = await auth_world.add_user(login="x.y", recovery_email="x@example.org")
    auth_world.hydra.add_login("lc-1", client_id="admin")
    auth_world.hydra.add_login("lc-2", client_id="admin")
    first = await auth_world.auth.log_in_with_password.execute(
        "lc-1", admin.login or "", PASSWORD, remember=False, ctx=CTX
    )
    assert first.second_factor is not None
    code = auth_world.otp.last("login2fa").code
    ticket = first.second_factor.ticket

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.log_in_with_otp.execute(
            "lc-2", admin.login or "", code, ticket=ticket, ctx=CTX
        )
    with pytest.raises(OtpInvalidError):
        await auth_world.auth.log_in_with_otp.execute(
            "lc-1", other.login or "", code, ticket=ticket, ctx=CTX
        )
    with pytest.raises(OtpInvalidError):
        await auth_world.auth.log_in_with_otp.execute(
            "lc-1", admin.login or "", code, ticket="unknown", ctx=CTX
        )


async def test_passwordless_otp_is_checked_against_the_client_role(
    auth_world: World,
) -> None:
    """ID-16: a student cannot reach the staff client with a code either."""
    student = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.hydra.add_login("lc-1", client_id="staff")
    await auth_world.auth.request_login_otp.execute(student.login or "", CTX)

    with pytest.raises(RoleMissingError):
        await auth_world.auth.log_in_with_otp.execute(
            "lc-1",
            student.login or "",
            auth_world.otp.last().code,
            ticket=None,
            ctx=CTX,
        )


async def test_staff_account_with_an_explicit_login_for_the_cli(
    auth_world: World,
) -> None:
    """`python -m app create-user --login ...` uses CreateStaffAccount."""
    created = await auth_world.auth.create_staff_account.execute(
        actor_id=None,
        last_name="Boss",
        first_name="Big",
        middle_name=None,
        email="boss@example.org",
        roles=[Role.ADMIN],
        login="Root.Admin",
    )

    assert created.user.login == "root.admin"
    assert created.user.otp_enabled is False
    with pytest.raises(LoginTakenError):
        await auth_world.auth.create_staff_account.execute(
            actor_id=None,
            last_name="Boss",
            first_name="Big",
            middle_name=None,
            email="boss2@example.org",
            roles=[Role.ADMIN],
            login="root.admin",
        )


def test_resources_map_to_mcp_servers() -> None:
    """MCP-3: audiences and resource URLs name the server."""
    assert server_from_resource("mcp-admin") == "admin"
    assert server_from_resource("https://mcp.ihsu.uz/mcp/lms/") == "lms"
    assert server_from_resource("https://api.example/mcp/student") == "student"
    assert server_from_resource("https://api.example/other") is None
    assert server_from_resource("student") is None
