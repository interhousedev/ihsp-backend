"""ID-16: Hydra's login, consent and logout URLs answer with redirects.

The browser is sent to the static login app only when a form is really needed.
"""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.application.start_login_session import (
    SSO_SESSION_SECONDS,
)
from app.modules.identity.domain.errors import HydraUnavailableError
from app.modules.identity.ports.hydra_gateway import LoginRequest, LogoutRequest
from app.shared.actor import Role
from tests.identity.support import PASSWORD, World

import pytest

ID_URL = "http://localhost:3001"
CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


# - - - Login - - -


async def test_login_without_a_hydra_session_goes_to_the_form(
    auth_world: World,
) -> None:
    """Nothing to skip: the static login page with the challenge."""
    auth_world.hydra.add_login("lc-1")

    target = await auth_world.auth.route_login_request.execute("lc-1")

    parsed = urlparse(target)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{ID_URL}/login/"
    assert "accept_login" not in auth_world.hydra.names()


async def test_the_form_url_says_which_client_asks(auth_world: World) -> None:
    """The page draws the form at once; no request is needed for the client name."""
    auth_world.hydra.add_login("lc-1", client_id="staff")

    target = await auth_world.auth.route_login_request.execute("lc-1")

    assert parse_qs(urlparse(target).query) == {
        "login_challenge": ["lc-1"],
        "client_id": ["staff"],
        "client_name": ["Client staff"],
    }


async def test_login_with_a_good_hydra_session_continues_without_a_page(
    auth_world: World,
) -> None:
    """Single sign-on: the login is accepted on the server."""
    user = await auth_world.add_user()
    auth_world.add_session(user, hydra_sid="sid-1")
    auth_world.hydra.add_login(
        "lc-1", skip=True, subject=str(user.id), session_id="sid-1"
    )

    target = await auth_world.auth.route_login_request.execute("lc-1")

    assert target == "https://hydra/continue?login_verifier=lc-1"


async def test_login_challenge_is_url_encoded_on_the_way_to_the_form(
    auth_world: World,
) -> None:
    """Hydra challenges are long opaque strings; nothing in them may break the URL."""
    challenge = "a+b/c=d&e f"
    auth_world.hydra.add_login(challenge)

    target = await auth_world.auth.route_login_request.execute(challenge)

    assert parse_qs(urlparse(target).query)["login_challenge"] == [challenge]


async def test_a_stale_hydra_session_restarts_the_flow_with_prompt_login(
    auth_world: World,
) -> None:
    """Hydra offers `skip` but the session is no good (a teacher at Administration).

    The login request restarts with `prompt=login`, so the user types the credentials
    once; accepting a different subject later would show the form twice.
    """
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    auth_world.add_session(teacher, hydra_sid="sid-1")
    auth_world.hydra.add_login(
        "lc-1",
        client_id="admin",
        skip=True,
        subject=str(teacher.id),
        session_id="sid-1",
        request_url="http://hydra/oauth2/auth?client_id=admin&state=abcdefgh",
    )

    target = await auth_world.auth.route_login_request.execute("lc-1")

    parsed = urlparse(target)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "http://hydra/oauth2/auth"
    )
    assert parse_qs(parsed.query) == {
        "client_id": ["admin"],
        "state": ["abcdefgh"],
        "prompt": ["login"],
    }
    assert "accept_login" not in auth_world.hydra.names()


async def test_restart_replaces_an_existing_prompt(auth_world: World) -> None:
    """`prompt=consent login` or `prompt=none` never survives the restart."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    auth_world.hydra.add_login(
        "lc-1",
        client_id="admin",
        skip=True,
        subject=str(teacher.id),
        request_url="http://hydra/oauth2/auth?prompt=consent&state=abcdefgh",
    )

    target = await auth_world.auth.route_login_request.execute("lc-1")

    assert parse_qs(urlparse(target).query)["prompt"] == ["login"]


async def test_a_used_login_challenge_follows_the_redirect_hydra_gave(
    auth_world: World,
) -> None:
    """410 from Hydra (reload, back button): start over where Hydra says."""
    auth_world.hydra.add_login("lc-1")
    auth_world.hydra.used.add("lc-1")

    target = await auth_world.auth.route_login_request.execute("lc-1")

    assert target == "https://hydra/restart"


async def test_login_falls_back_to_the_form_when_hydra_fails(
    auth_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page asks Hydra again and shows its own retry screen."""
    auth_world.hydra.add_login("lc-1")

    async def broken(challenge: str) -> LoginRequest:
        raise HydraUnavailableError(support_details="down")

    monkeypatch.setattr(auth_world.hydra, "get_login_request", broken)

    target = await auth_world.auth.route_login_request.execute("lc-1")

    assert target == f"{ID_URL}/login/?login_challenge=lc-1"


# - - - Remember - - -


async def test_a_login_is_always_remembered_for_single_sign_on(
    auth_world: World,
) -> None:
    """Without `remember` Hydra would set no cookie and every app would ask again."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")

    await auth_world.auth.log_in_with_password.execute(
        "lc-1", user.login or "", PASSWORD, remember=False, ctx=CTX
    )

    accepted = auth_world.hydra.last("accept_login")
    assert accepted["remember"] is True
    assert accepted["remember_for"] == SSO_SESSION_SECONDS


async def test_remember_me_keeps_the_hydra_session_for_a_year(
    auth_world: World,
) -> None:
    """The checkbox remembers the device for IHSP_IDENTITY__REMEMBER_DAYS (365)."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")

    await auth_world.auth.log_in_with_password.execute(
        "lc-1", user.login or "", PASSWORD, remember=True, ctx=CTX
    )

    accepted = auth_world.hydra.last("accept_login")
    assert accepted["remember"] is True
    assert accepted["remember_for"] == 365 * 24 * 3600
    session = next(iter(auth_world.store.sessions.values()))
    assert session.expires_at - auth_world.clock.now() >= timedelta(days=365)


async def test_a_remembered_device_skips_the_password_a_year_later(
    auth_world: World,
) -> None:
    """my.iht lost its tokens: Hydra skip=true is accepted without the form."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")
    await auth_world.auth.log_in_with_password.execute(
        "lc-1", user.login or "", PASSWORD, remember=True, ctx=CTX
    )
    auth_world.clock.advance(days=300)
    auth_world.hydra.add_login(
        "lc-2", skip=True, subject=str(user.id), session_id="hydra-sid-lc-1"
    )

    info = await auth_world.auth.get_login_info.execute("lc-2")

    assert info.skip and info.redirect_to
    assert auth_world.hydra.last("accept_login")["remember_for"] == 365 * 24 * 3600


async def test_a_ticket_signs_in_once_on_a_remembered_device(
    auth_world: World,
) -> None:
    """Registration/reset without a challenge: IHT ID redeems it on its own login."""
    from app.modules.identity.domain.errors import LoginTicketInvalidError

    user = await auth_world.add_user()
    acceptor = auth_world.auth.login_acceptor
    ticket = await acceptor.issue_ticket(user.id, amr=["pwd"])
    auth_world.hydra.add_login("lc-1")

    redirect = await acceptor.redeem_ticket("lc-1", ticket, ip=None, user_agent=None)

    accepted = auth_world.hydra.last("accept_login")
    assert redirect
    assert accepted["subject"] == str(user.id)
    assert accepted["remember_for"] == 365 * 24 * 3600
    auth_world.hydra.add_login("lc-2")
    with pytest.raises(LoginTicketInvalidError):
        await acceptor.redeem_ticket("lc-2", ticket, ip=None, user_agent=None)


# - - - Consent - - -


async def test_first_party_consent_is_accepted_on_the_server(
    auth_world: World,
) -> None:
    """No consent page for our own apps."""
    user = await auth_world.add_user()
    session = auth_world.add_session(user)
    auth_world.hydra.add_consent(
        "cc-1",
        client_id="sp",
        subject=str(user.id),
        requested_scope=("openid", "offline_access"),
        context={"session_id": str(session.id)},
    )

    target = await auth_world.auth.route_consent_request.execute("cc-1")

    assert target == "https://hydra/code?consent_verifier=cc-1"
    assert auth_world.hydra.last("accept_consent")["grant_audience"] == ["ihsp-api"]


async def test_library_silent_sign_in_gets_its_consent_accepted(
    auth_world: World,
) -> None:
    """Silent SSO (prompt=none) of the library accepts first-party consent.

    The consent screen is not shown.
    """
    user = await auth_world.add_user(roles={Role.STUDENT})
    session = auth_world.add_session(user)
    auth_world.hydra.add_consent(
        "cc-1",
        client_id="library",
        subject=str(user.id),
        request_url="https://hydra/oauth2/auth?client_id=library&prompt=none",
        requested_scope=("openid", "offline_access"),
        context={"session_id": str(session.id)},
    )

    target = await auth_world.auth.route_consent_request.execute("cc-1")

    assert target == "https://hydra/code?consent_verifier=cc-1"
    assert auth_world.hydra.last("accept_consent")["grant_audience"] == ["ihsp-api"]


async def test_an_mcp_client_gets_the_consent_page(auth_world: World) -> None:
    """Only third-party clients are asked."""
    user = await auth_world.add_user()
    auth_world.hydra.add_consent(
        "cc-1", client_id="claude-desktop", subject=str(user.id)
    )

    target = await auth_world.auth.route_consent_request.execute("cc-1")

    assert target == f"{ID_URL}/consent/?consent_challenge=cc-1"
    assert "accept_consent" not in auth_world.hydra.names()


async def test_a_used_consent_challenge_follows_the_redirect_hydra_gave(
    auth_world: World,
) -> None:
    """410: the consent was handled before."""
    auth_world.hydra.add_consent("cc-1", client_id="sp", subject="x")
    auth_world.hydra.used.add("cc-1")

    target = await auth_world.auth.route_consent_request.execute("cc-1")

    assert target == "https://hydra/restart"


# - - - Logout - - -


async def test_logout_is_accepted_on_the_server(auth_world: World) -> None:
    """The logout page only ever accepted and followed `redirect_to`."""
    auth_world.hydra.logout_requests["lo-1"] = LogoutRequest(
        challenge="lo-1", subject=None, sid=None
    )

    target = await auth_world.auth.route_logout_request.execute("lo-1")

    assert target == "https://hydra/after-logout"


async def test_logout_falls_back_to_the_page_when_hydra_fails(
    auth_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page shows the failure with a retry."""

    async def broken(challenge: str) -> LogoutRequest:
        raise HydraUnavailableError(support_details="down")

    monkeypatch.setattr(auth_world.hydra, "get_logout_request", broken)

    target = await auth_world.auth.route_logout_request.execute("lo-1")

    assert target == f"{ID_URL}/logout/?logout_challenge=lo-1"
