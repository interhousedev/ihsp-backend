"""ID-23, ID-24, ID-26, UF-ID-07, UF-ID-08, UF-ID-10: account recovery."""

from datetime import timedelta

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpInvalidError, PasswordPolicyError
from app.shared.actor import Role
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


async def test_password_reset_changes_the_password_and_logs_out_everywhere(
    auth_world: World,
) -> None:
    """ID-23: a code to the recovery email; all sessions are revoked afterwards."""
    user = await auth_world.add_user(auth_epoch=1)
    session = auth_world.add_session(user)
    connector = auth_world.add_connector(user)
    auth_world.add_link(user, 555)

    await auth_world.auth.request_password_reset.execute(user.login or "", CTX)
    code = auth_world.otp.last("pw-reset").code
    assert auth_world.otp.last("pw-reset").channels == ("email",)
    await auth_world.auth.confirm_password_reset.execute(
        user.recovery_email or "", code, "N3wStrongPass", CTX
    )

    stored = auth_world.user(user.id)
    assert await auth_world.auth.hasher.verify(stored.password_hash, "N3wStrongPass")
    assert stored.auth_epoch > 1
    assert auth_world.store.sessions[session.id].revoked_at is not None
    assert auth_world.store.connectors[connector.id].revoked_at is not None
    assert 555 in auth_world.store.links  # Telegram links stay (ID-23)
    assert "password.reset" in auth_world.store.audit_types(user.id)
    assert auth_world.hydra.last("revoke_login_sessions")["subject"] == str(user.id)


async def test_password_reset_request_is_silent_for_unknown_accounts(
    auth_world: World,
) -> None:
    """UF-ID-07: the page always says "If the account exists..."."""
    await auth_world.auth.request_password_reset.execute("nobody.here", CTX)
    await auth_world.auth.request_password_reset.execute("nobody@example.org", CTX)

    assert auth_world.otp.codes == []


async def test_password_reset_does_nothing_for_administration(
    auth_world: World,
) -> None:
    """ID-23: Administration accounts are reset by another administrator."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)

    await auth_world.auth.request_password_reset.execute(admin.login or "", CTX)
    assert auth_world.otp.codes == []

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.confirm_password_reset.execute(
            admin.login or "", "123456", "N3wStrongPass", CTX
        )


async def test_password_reset_without_a_verified_email_sends_nothing(
    auth_world: World,
) -> None:
    """UF-ID-07 2a: never-activated staff need a new activation link."""
    user = await auth_world.add_user(recovery_email_verified_at=None)

    await auth_world.auth.request_password_reset.execute(user.login or "", CTX)

    assert auth_world.otp.codes == []


async def test_password_reset_accepts_the_email_instead_of_the_login(
    auth_world: World,
) -> None:
    """UF-ID-07 1: login or recovery email."""
    user = await auth_world.add_user()

    await auth_world.auth.request_password_reset.execute(
        (user.recovery_email or "").upper(), CTX
    )

    assert auth_world.otp.count("pw-reset") == 1


async def test_password_reset_with_a_weak_password_keeps_the_code_usable(
    auth_world: World,
) -> None:
    """UF-ID-07 3: rules are checked; the code is not spent by a policy error."""
    user = await auth_world.add_user()
    await auth_world.auth.request_password_reset.execute(user.login or "", CTX)
    code = auth_world.otp.last().code

    with pytest.raises(PasswordPolicyError):
        await auth_world.auth.confirm_password_reset.execute(
            user.login or "", code, "weak", CTX
        )
    await auth_world.auth.confirm_password_reset.execute(
        user.login or "", code, "N3wStrongPass", CTX
    )


async def test_password_reset_with_a_wrong_code_fails(auth_world: World) -> None:
    """UF-ID-07 3a."""
    user = await auth_world.add_user()
    await auth_world.auth.request_password_reset.execute(user.login or "", CTX)

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.confirm_password_reset.execute(
            user.login or "",
            "999999" if auth_world.otp.last().code != "999999" else "888888",
            "N3wStrongPass",
            CTX,
        )


# - - - OTP reset - - -


async def request_and_confirm_otp_reset(world: World, login: str):
    """Run both steps of UF-ID-08 and return effective_at."""
    await world.auth.request_otp_reset.execute(login, CTX)
    code = world.otp.last("otp-reset").code
    return await world.auth.confirm_otp_reset.execute(login, code, CTX)


async def test_otp_reset_takes_effect_after_24_hours(auth_world: World) -> None:
    """ID-24: the Telegram links are removed by the job once the delay has passed."""
    user = await auth_world.add_user(otp_enabled=True)
    auth_world.add_link(user, 555)
    auth_world.add_link(user, 556)

    effective_at = await request_and_confirm_otp_reset(auth_world, user.login or "")

    assert effective_at == auth_world.clock.now() + timedelta(hours=24)
    assert auth_world.store.notification_types() == ["otp_reset_requested"]
    payload = auth_world.store.notifications[0].payload
    assert payload["effective_at"] == effective_at.isoformat()
    assert payload["request_id"] == str(auth_world.user(user.id).otp_reset_request_id)

    assert await auth_world.auth.apply_otp_resets.execute() == 0
    assert len(auth_world.store.links) == 2

    auth_world.clock.advance(hours=24, seconds=1)
    assert await auth_world.auth.apply_otp_resets.execute() == 1

    stored = auth_world.user(user.id)
    assert auth_world.store.links == {}
    assert stored.otp_reset_effective_at is None
    assert stored.otp_via_email is True  # OTP stays on with the email channel
    assert "otp.reset_applied" in auth_world.store.audit_types(user.id)


async def test_cancel_stops_the_reset_and_warns_by_email(auth_world: World) -> None:
    """UF-ID-08 4a: the Cancel button in Telegram."""
    user = await auth_world.add_user(otp_enabled=True)
    auth_world.add_link(user, 555)
    await request_and_confirm_otp_reset(auth_world, user.login or "")
    request_id = auth_world.user(user.id).otp_reset_request_id
    assert request_id is not None

    await auth_world.auth.cancel_otp_reset.execute(request_id, CTX)
    auth_world.clock.advance(hours=25)
    await auth_world.auth.apply_otp_resets.execute()

    assert 555 in auth_world.store.links
    assert auth_world.user(user.id).otp_reset_request_id is None
    (notice,) = auth_world.email.to(user.recovery_email or "", "notice")
    assert notice["text_key"] == "id-mail-notice-otp-cancelled"


async def test_cancelling_an_unknown_request_is_ignored(auth_world: World) -> None:
    """The endpoint answers 204 either way."""
    from app.shared.ids import new_id

    await auth_world.auth.cancel_otp_reset.execute(new_id(), CTX)

    assert auth_world.store.audits == []


async def test_otp_reset_is_refused_for_administration(auth_world: World) -> None:
    """UF-ID-08 1a: another Administration member resets it."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    auth_world.add_link(admin, 555)

    await auth_world.auth.request_otp_reset.execute(admin.login or "", CTX)

    assert auth_world.otp.codes == []


async def test_otp_reset_needs_a_telegram_link_to_reset(auth_world: World) -> None:
    """Nothing to reset without linked accounts: no code is sent."""
    user = await auth_world.add_user(otp_enabled=True)

    await auth_world.auth.request_otp_reset.execute(user.login or "", CTX)

    assert auth_world.otp.codes == []


# - - - Forgotten login - - -


async def test_login_reminder_emails_the_login(auth_world: World) -> None:
    """ID-26: the login goes to the recovery email."""
    user = await auth_world.add_user()

    await auth_world.auth.send_login_reminder.execute(user.recovery_email or "", CTX)

    (params,) = auth_world.email.to(user.recovery_email or "", "login_reminder")
    assert params == {"login": user.login}


async def test_login_reminder_is_silent_for_unknown_addresses(
    auth_world: World,
) -> None:
    """UF-ID-10: the page shows the same message either way."""
    await auth_world.auth.send_login_reminder.execute("nobody@example.org", CTX)

    assert auth_world.email.sent == []


async def test_login_reminder_survives_a_broken_mail_relay(auth_world: World) -> None:
    """A relay failure must not reveal that the account exists."""
    user = await auth_world.add_user()
    auth_world.email.fail = True

    await auth_world.auth.send_login_reminder.execute(user.recovery_email or "", CTX)


# - - - confirm steps answer alike for any login - - -


async def test_password_reset_confirm_for_an_unknown_login_counts_attempts(
    auth_world: World,
) -> None:
    """Review 2026-10-11: the confirm step does not reveal if the account exists."""
    with pytest.raises(OtpInvalidError) as caught:
        await auth_world.auth.confirm_password_reset.execute(
            "nobody.here", "123456", "N3wStrongPass", CTX
        )
    assert caught.value.params == {"attempts_left": 2}

    user = await auth_world.add_user()
    await auth_world.auth.request_password_reset.execute(user.login or "", CTX)
    with pytest.raises(OtpInvalidError) as caught:
        await auth_world.auth.confirm_password_reset.execute(
            user.login or "",
            "999999" if auth_world.otp.last().code != "999999" else "888888",
            "N3wStrongPass",
            CTX,
        )
    assert caught.value.params == {"attempts_left": 2}


async def test_otp_reset_confirm_is_limited_per_login_across_ips(
    auth_world: World,
) -> None:
    """Review 2026-10-11: 15 confirms per login per hour, whatever the IP."""
    from app.shared.base_error import RateLimitedError

    for n in range(15):
        ctx = RequestContext(ip=f"198.51.100.{n}", user_agent="pytest")
        with pytest.raises(OtpInvalidError):
            await auth_world.auth.confirm_otp_reset.execute(
                "nobody.here", "000000", ctx
            )

    with pytest.raises(RateLimitedError):
        await auth_world.auth.confirm_otp_reset.execute(
            "nobody.here", "000000", RequestContext(ip="192.0.2.1", user_agent="pytest")
        )
