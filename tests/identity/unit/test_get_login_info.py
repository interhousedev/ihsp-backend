"""ID-16: single sign-on."""

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
    assert info.requires_second_factor is False
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
