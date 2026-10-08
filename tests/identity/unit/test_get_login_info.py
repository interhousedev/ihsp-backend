"""ID-11, ID-16: single sign-on and the admin 12-hour rule."""

from datetime import timedelta

from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from tests.identity.support import World


async def test_login_info_describes_the_client_without_skipping(
    auth_world: World,
) -> None:
    """The page shows the client name and whether a second factor will follow."""
    auth_world.hydra.add_login("lc-1", client_id="admin")

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert (info.client_id, info.client_name) == ("admin", "Client admin")
    assert info.skip is False
    assert info.requires_second_factor is True
    assert info.redirect_to is None


async def test_a_good_hydra_session_is_accepted_without_a_form(
    auth_world: World,
) -> None:
    """ID-16: SSO skips the login page when the session is still valid."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user, hydra_sid="sid-1", amr=["pwd"])
    auth_world.hydra.add_login(
        "lc-1", skip=True, subject=str(user.id), session_id="sid-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert info.skip is True
    assert info.redirect_to == "https://hydra/continue?login_verifier=lc-1"
    context = auth_world.hydra.last("accept_login")["context"]
    assert context["session_id"] == str(session.id)


async def test_admin_client_does_not_skip_when_the_otp_is_13_hours_old(
    auth_world: World,
) -> None:
    """ID-11: password + OTP older than 12 hours means a fresh login."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    mfa_at = auth_world.clock.now() - timedelta(hours=13)
    auth_world.add_session(admin, hydra_sid="sid-1", amr=["pwd", "otp"], mfa_at=mfa_at)
    auth_world.hydra.add_login(
        "lc-1", client_id="admin", skip=True, subject=str(admin.id), session_id="sid-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert info.skip is False
    assert info.redirect_to is None
    assert "accept_login" not in auth_world.hydra.names()


async def test_admin_client_skips_when_the_otp_is_one_hour_old(
    auth_world: World,
) -> None:
    """ID-11: a recent password + OTP login is reused."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    mfa_at = auth_world.clock.now() - timedelta(hours=1)
    auth_world.add_session(admin, hydra_sid="sid-1", amr=["pwd", "otp"], mfa_at=mfa_at)
    auth_world.hydra.add_login(
        "lc-1", client_id="admin", skip=True, subject=str(admin.id), session_id="sid-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert info.redirect_to is not None


async def test_telegram_session_never_reaches_the_admin_client(
    auth_world: World,
) -> None:
    """ID-11: a session without mfa_at is not good enough for admin."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    auth_world.add_session(admin, hydra_sid="sid-1", amr=["tg"])
    auth_world.hydra.add_login(
        "lc-1", client_id="admin", skip=True, subject=str(admin.id), session_id="sid-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert info.redirect_to is None


async def test_revoked_session_is_not_reused_for_single_sign_on(
    auth_world: World,
) -> None:
    """GEN-5: after a block or logout the login form is shown again."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user, hydra_sid="sid-1")
    session.revoked_at = auth_world.clock.now()
    auth_world.hydra.add_login(
        "lc-1", skip=True, subject=str(user.id), session_id="sid-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert info.redirect_to is None


async def test_blocked_user_is_not_reused_for_single_sign_on(
    auth_world: World,
) -> None:
    """GEN-5: a blocked account never skips the form."""
    user = await auth_world.add_user(status=UserStatus.BLOCKED)
    auth_world.add_session(user, hydra_sid="sid-1")
    auth_world.hydra.add_login(
        "lc-1", skip=True, subject=str(user.id), session_id="sid-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-1")

    assert info.redirect_to is None
