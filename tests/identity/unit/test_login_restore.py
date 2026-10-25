"""ID-29: logging in to an account scheduled for deletion offers to restore it."""

from datetime import date, timedelta

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import InvalidCredentialsError
from app.shared.contracts.identity import UserStatus
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest/1.0")


async def pending_user(world: World, **fields: object):
    """A student whose deletion was requested 10 days ago."""
    requested = world.clock.now() - timedelta(days=10)
    return await world.add_user(
        status=UserStatus.PENDING_DELETION, deletion_requested_at=requested, **fields
    )


async def password_login(world: World, login: str, challenge: str = "lc-1"):
    """Run the password login use case."""
    return await world.auth.log_in_with_password.execute(
        challenge, login, PASSWORD, remember=True, ctx=CTX
    )


async def test_password_login_offers_the_restore_instead_of_failing(
    auth_world: World,
) -> None:
    """No session yet: a ticket and the purge date (request + 30 days)."""
    user = await pending_user(auth_world)
    auth_world.hydra.add_login("lc-1")

    result = await password_login(auth_world, user.login or "")

    assert result.redirect_to is None
    assert result.restore is not None
    requested = auth_world.clock.now() - timedelta(days=10)
    assert result.restore.deletes_on == requested.date() + timedelta(days=30)
    assert auth_world.store.sessions == {}
    assert "accept_login" not in auth_world.hydra.names()


async def test_restore_cancels_the_deletion_and_finishes_the_login(
    auth_world: World,
) -> None:
    """Restore: status active again, the Hydra login accepted with amr pwd."""
    user = await pending_user(auth_world)
    auth_world.hydra.add_login("lc-1", client_id="sp")
    offer = await password_login(auth_world, user.login or "")
    assert offer.restore is not None

    result = await auth_world.auth.restore_account_at_login.execute(
        "lc-1", offer.restore.ticket, ctx=CTX
    )

    assert result.redirect_to == "https://hydra/continue?login_verifier=lc-1"
    stored = auth_world.user(user.id)
    assert stored.status == UserStatus.ACTIVE
    assert stored.deletion_requested_at is None
    assert auth_world.hydra.last("accept_login")["amr"] == ["pwd"]
    assert "account.restored" in auth_world.store.audit_types(user.id)
    with pytest.raises(InvalidCredentialsError):  # the ticket is single-use
        await auth_world.auth.restore_account_at_login.execute(
            "lc-1", offer.restore.ticket, ctx=CTX
        )


async def test_the_ticket_is_bound_to_its_login_challenge(auth_world: World) -> None:
    """A ticket alone (another challenge) restores nothing."""
    user = await pending_user(auth_world)
    auth_world.hydra.add_login("lc-1")
    auth_world.hydra.add_login("lc-2")
    offer = await password_login(auth_world, user.login or "")
    assert offer.restore is not None

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.restore_account_at_login.execute(
            "lc-2", offer.restore.ticket, ctx=CTX
        )
    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.restore_account_at_login.execute(
            "lc-1", "made-up", ctx=CTX
        )

    assert auth_world.user(user.id).status == UserStatus.PENDING_DELETION


async def test_decline_keeps_the_deletion_and_rejects_the_login(
    auth_world: World,
) -> None:
    """Keep deleted: the challenge is rejected, the account stays pending."""
    user = await pending_user(auth_world)
    auth_world.hydra.add_login("lc-1")
    offer = await password_login(auth_world, user.login or "")
    assert offer.restore is not None

    redirect = await auth_world.auth.decline_account_restore.execute(
        "lc-1", offer.restore.ticket
    )

    assert redirect == "https://hydra/rejected?challenge=lc-1"
    assert auth_world.user(user.id).status == UserStatus.PENDING_DELETION


async def test_a_wrong_password_still_fails_for_a_pending_account(
    auth_world: World,
) -> None:
    """The restore offer needs the right password."""
    user = await pending_user(auth_world)
    auth_world.hydra.add_login("lc-1")

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.log_in_with_password.execute(
            "lc-1", user.login or "", "Wr0ngPassword", remember=False, ctx=CTX
        )


async def test_otp_login_offers_the_restore_too(auth_world: World) -> None:
    """Passwordless: the code is sent and accepted, then the restore is offered."""
    user = await pending_user(auth_world, otp_enabled=True, otp_via_email=True)
    auth_world.hydra.add_login("lc-1")
    await auth_world.auth.request_login_otp.execute(user.login or "", CTX)

    result = await auth_world.auth.log_in_with_otp.execute(
        "lc-1", user.login or "", auth_world.otp.last().code, ticket=None, ctx=CTX
    )

    assert result.restore is not None
    restored = await auth_world.auth.restore_account_at_login.execute(
        "lc-1", result.restore.ticket, ctx=CTX
    )
    assert restored.redirect_to
    assert auth_world.hydra.last("accept_login")["amr"] == ["otp"]


async def test_a_deleted_account_of_the_old_flow_still_cannot_log_in(
    auth_world: World,
) -> None:
    """Status deleted (files already gone): no restore offer, a plain failure."""
    user = await auth_world.add_user(
        status=UserStatus.DELETED, deleted_at=auth_world.clock.now()
    )
    auth_world.hydra.add_login("lc-1")

    with pytest.raises(InvalidCredentialsError):
        await password_login(auth_world, user.login or "")


async def test_the_telegram_notice_names_the_date(auth_world: World) -> None:
    """Every linked chat gets the date and a restore button."""
    user = await auth_world.add_user(preferences={"locale": "en"})
    auth_world.add_link(user, 555)
    auth_world.add_link(user, 556)
    auth_world.telegram.failing.add(555)

    await auth_world.auth.deletion_telegram_notice(user.id, date(2026, 11, 13))

    ((chat_id, text, buttons),) = auth_world.telegram.messages
    assert chat_id == 556
    assert "2026-11-13" in text
    assert buttons and buttons[0][0]["url"].endswith("/login/")
