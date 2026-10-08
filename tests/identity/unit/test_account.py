"""ID-17, ID-21, ID-22, ID-25, WEB-17, GEN-6: the /v1/id/me use cases."""

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    EmailTakenError,
    InvalidCredentialsError,
    OtpChannelMissingError,
    OtpInvalidError,
    OtpMandatoryError,
    PasswordPolicyError,
)
from app.modules.identity.domain.session import LoginSession
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.base_error import NotFoundError, ValidationFailedError
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def actor_of(user: User, session: LoginSession | None = None) -> Actor:
    """The caller, optionally with a current session."""
    return Actor(
        user_id=user.id,
        roles=frozenset(user.roles),
        session_id=session.id if session else None,
    )


# - - - Account and preferences - - -


async def test_me_shows_the_account_with_telegram_and_mailbox(
    auth_world: World,
) -> None:
    """WEB-16: profile, mailbox for students, Telegram accounts."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555, username="ali")

    view = await auth_world.auth.get_me.execute(actor_of(user))

    assert view.user.id == user.id
    assert view.mailbox == f"{user.login}@mail.ihsu.uz"
    assert [link.telegram_user_id for link in view.telegram] == [555]


async def test_teachers_have_no_mailbox(auth_world: World) -> None:
    """MAIL-1: every student gets {login}@mail.ihsu.uz."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})

    view = await auth_world.auth.get_me.execute(actor_of(teacher))

    assert view.mailbox is None


async def test_preferences_patch_merges_and_returns_the_whole_document(
    auth_world: World,
) -> None:
    """WEB-17: only the sent keys change."""
    user = await auth_world.add_user(preferences={"locale": "uz"})

    result = await auth_world.auth.update_preferences.execute(
        actor_of(user), {"theme": "dark", "alerts_gpa_below": 4.0}
    )

    assert (result.locale, result.theme, result.alerts_gpa_below) == ("uz", "dark", 4.0)
    assert auth_world.user(user.id).preferences == {
        "locale": "uz",
        "theme": "dark",
        "alerts_gpa_below": 4.0,
    }


async def test_explicit_null_clears_a_nullable_preference(auth_world: World) -> None:
    """WEB-17: switching a threshold off sends null."""
    user = await auth_world.add_user(preferences={"alerts_gpa_below": 4.0})

    result = await auth_world.auth.update_preferences.execute(
        actor_of(user), {"alerts_gpa_below": None}
    )

    assert result.alerts_gpa_below is None


@pytest.mark.parametrize(
    "patch", [{"theme": "neon"}, {"marks_values": "all"}, {"unknown_key": 1}]
)
async def test_invalid_preferences_are_refused(auth_world: World, patch: dict) -> None:
    """The patch is validated against UserPreferences before it is stored."""
    user = await auth_world.add_user()

    with pytest.raises(ValidationFailedError):
        await auth_world.auth.update_preferences.execute(actor_of(user), patch)

    assert auth_world.user(user.id).preferences == {}


# - - - Password and sessions - - -


async def test_changing_the_password_keeps_only_the_current_session(
    auth_world: World,
) -> None:
    """ID-17: other devices are logged out, the current one stays."""
    user = await auth_world.add_user()
    current = auth_world.add_session(user, hydra_sid="sid-a")
    other = auth_world.add_session(user, hydra_sid="sid-b")

    await auth_world.auth.change_password.execute(
        actor_of(user, current), PASSWORD, "N3wStrongPass", CTX
    )

    stored = auth_world.user(user.id)
    assert await auth_world.auth.hasher.verify(stored.password_hash, "N3wStrongPass")
    assert auth_world.store.sessions[current.id].revoked_at is None
    assert auth_world.store.sessions[other.id].revoked_at is not None
    assert await auth_world.redis.exists(f"auth:revoked:{other.id}")
    assert auth_world.hydra.last("revoke_login_sessions") == {
        "subject": None,
        "sid": "sid-b",
    }
    assert "password.changed" in auth_world.store.audit_types(user.id)


async def test_wrong_current_password_is_refused(auth_world: World) -> None:
    """ID-4: the old password is required."""
    user = await auth_world.add_user()

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.change_password.execute(
            actor_of(user), "Wr0ngPassword", "N3wStrongPass", CTX
        )


async def test_weak_new_password_lists_the_broken_rules(auth_world: World) -> None:
    """ID-4: 8 characters, a digit, upper and lower case."""
    user = await auth_world.add_user()

    with pytest.raises(PasswordPolicyError) as caught:
        await auth_world.auth.change_password.execute(
            actor_of(user), PASSWORD, "short", CTX
        )

    assert set(caught.value.params["errors"]) == {
        "id-password-too-short",
        "id-password-no-digit",
        "id-password-no-upper",
    }


async def test_sessions_list_marks_the_current_device(auth_world: World) -> None:
    """UF-ID-11: device, IP and the current session."""
    user = await auth_world.add_user()
    current = auth_world.add_session(user)
    other = auth_world.add_session(user)
    gone = auth_world.add_session(user)
    gone.revoked_at = auth_world.clock.now()

    views = await auth_world.auth.list_sessions.execute(actor_of(user, current))

    assert {v.session.id: v.current for v in views} == {
        current.id: True,
        other.id: False,
    }


async def test_revoking_one_session_logs_that_device_out(auth_world: World) -> None:
    """ID-17: the session is revoked in the database, Redis and Hydra."""
    user = await auth_world.add_user()
    current = auth_world.add_session(user)
    other = auth_world.add_session(user, hydra_sid="sid-x")

    await auth_world.auth.revoke_session.execute(actor_of(user, current), other.id, CTX)

    assert auth_world.store.sessions[other.id].revoked_at is not None
    assert await auth_world.redis.exists(f"auth:revoked:{other.id}")
    assert auth_world.hydra.last("revoke_login_sessions")["sid"] == "sid-x"
    assert "session.revoked" in auth_world.store.audit_types(user.id)


async def test_cannot_revoke_a_session_of_another_user(auth_world: World) -> None:
    """ID-17: sessions are private."""
    user = await auth_world.add_user()
    stranger = await auth_world.add_user(login="x.y", recovery_email="x@example.org")
    theirs = auth_world.add_session(stranger)

    with pytest.raises(NotFoundError):
        await auth_world.auth.revoke_session.execute(actor_of(user), theirs.id, CTX)

    assert auth_world.store.sessions[theirs.id].revoked_at is None


async def test_log_out_everywhere_else_keeps_the_current_session(
    auth_world: World,
) -> None:
    """UF-ID-11: Log out everywhere else."""
    user = await auth_world.add_user()
    current = auth_world.add_session(user)
    others = [auth_world.add_session(user) for _ in range(2)]

    count = await auth_world.auth.revoke_other_sessions.execute(
        actor_of(user, current), CTX
    )

    assert count == 2
    assert auth_world.store.sessions[current.id].revoked_at is None
    assert all(auth_world.store.sessions[s.id].revoked_at for s in others)


# - - - Telegram accounts - - -


async def test_otp_delivery_can_be_switched_per_account(auth_world: World) -> None:
    """ID-21: the per-account OTP toggle."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    link = await auth_world.auth.update_telegram_account.execute(
        actor_of(user), 555, otp_delivery=False
    )

    assert link.otp_delivery is False
    assert auth_world.store.links[555].otp_delivery is False


async def test_unlinking_deletes_the_link_and_is_audited(auth_world: World) -> None:
    """ID-21: unlinking logs that account out of the bot."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    await auth_world.auth.unlink_telegram_account.execute(actor_of(user), 555, CTX)

    assert auth_world.store.links == {}
    assert "telegram.unlinked" in auth_world.store.audit_types(user.id)


async def test_cannot_touch_the_telegram_account_of_another_user(
    auth_world: World,
) -> None:
    """ID-18: links are private."""
    owner = await auth_world.add_user()
    stranger = await auth_world.add_user(login="x.y", recovery_email="x@example.org")
    auth_world.add_link(owner, 555)

    with pytest.raises(NotFoundError):
        await auth_world.auth.unlink_telegram_account.execute(
            actor_of(stranger), 555, CTX
        )
    with pytest.raises(NotFoundError):
        await auth_world.auth.update_telegram_account.execute(
            actor_of(stranger), 555, otp_delivery=False
        )


# - - - OTP login settings - - -


async def test_enabling_otp_needs_the_test_code(auth_world: World) -> None:
    """UF-ID-06: a test code goes to the chosen channels; confirming enables OTP."""
    user = await auth_world.add_user()
    auth_world.add_link(user, 555)

    await auth_world.auth.enable_otp.execute(actor_of(user), via_email=True, ctx=CTX)
    sent = auth_world.otp.last("otp-enable")
    assert sent.channels == ("telegram", "email")
    assert auth_world.user(user.id).otp_enabled is False

    await auth_world.auth.confirm_otp_enable.execute(actor_of(user), sent.code, CTX)

    stored = auth_world.user(user.id)
    assert (stored.otp_enabled, stored.otp_via_email) == (True, True)
    assert "otp.enabled" in auth_world.store.audit_types(user.id)


async def test_wrong_confirmation_code_leaves_otp_off(auth_world: World) -> None:
    """UF-ID-06 step 3."""
    user = await auth_world.add_user()
    await auth_world.auth.enable_otp.execute(actor_of(user), via_email=True, ctx=CTX)
    good = auth_world.otp.last().code

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.confirm_otp_enable.execute(
            actor_of(user), "000000" if good != "000000" else "111111", CTX
        )

    assert auth_world.user(user.id).otp_enabled is False


async def test_enabling_otp_without_any_channel_is_refused(auth_world: World) -> None:
    """UF-ID-06 2: with no Telegram and no email there is nowhere to send codes."""
    user = await auth_world.add_user()

    with pytest.raises(OtpChannelMissingError):
        await auth_world.auth.enable_otp.execute(
            actor_of(user), via_email=False, ctx=CTX
        )


async def test_confirming_without_a_pending_request_fails(auth_world: World) -> None:
    """The choice of channels expires with the request."""
    user = await auth_world.add_user()

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.confirm_otp_enable.execute(actor_of(user), "123456", CTX)


async def test_disabling_otp_needs_the_password(auth_world: World) -> None:
    """UF-ID-06 1a."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.disable_otp.execute(actor_of(user), "Wr0ngPassword", CTX)
    await auth_world.auth.disable_otp.execute(actor_of(user), PASSWORD, CTX)

    stored = auth_world.user(user.id)
    assert (stored.otp_enabled, stored.otp_via_email) == (False, False)


async def test_administration_cannot_turn_otp_off(auth_world: World) -> None:
    """ID-11: OTP is mandatory for Administration."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)

    with pytest.raises(OtpMandatoryError):
        await auth_world.auth.disable_otp.execute(actor_of(admin), PASSWORD, CTX)

    assert auth_world.user(admin.id).otp_enabled is True


# - - - Recovery email - - -


async def test_email_change_sends_the_code_to_the_new_address_only(
    auth_world: World,
) -> None:
    """ID-25: password + a code sent to the new address; the old one gets a notice."""
    user = await auth_world.add_user()
    old = user.recovery_email or ""

    await auth_world.auth.request_email_change.execute(
        actor_of(user), PASSWORD, "New.Address@Example.org", CTX
    )
    assert auth_world.email.to(old, "otp") == []
    code = auth_world.email.last_code("new.address@example.org")

    await auth_world.auth.confirm_email_change.execute(actor_of(user), code, CTX)

    stored = auth_world.user(user.id)
    assert stored.recovery_email == "new.address@example.org"
    assert stored.recovery_email_verified_at == auth_world.clock.now()
    (notice,) = auth_world.email.to(old, "notice")
    assert notice["text_key"] == "id-mail-notice-email-changed"
    assert "email.changed" in auth_world.store.audit_types(user.id)


async def test_email_change_needs_the_password(auth_world: World) -> None:
    """ID-25: the current password."""
    user = await auth_world.add_user()

    with pytest.raises(InvalidCredentialsError):
        await auth_world.auth.request_email_change.execute(
            actor_of(user), "Wr0ngPassword", "new@example.org", CTX
        )

    assert auth_world.email.sent == []


async def test_email_of_another_account_cannot_be_used(auth_world: World) -> None:
    """ID-4: one recovery email per account."""
    user = await auth_world.add_user()
    other = await auth_world.add_user(login="x.y", recovery_email="taken@example.org")

    with pytest.raises(EmailTakenError):
        await auth_world.auth.request_email_change.execute(
            actor_of(user), PASSWORD, other.recovery_email or "", CTX
        )


async def test_wrong_email_code_keeps_the_old_address(auth_world: World) -> None:
    """ID-25: the code must match."""
    user = await auth_world.add_user()
    await auth_world.auth.request_email_change.execute(
        actor_of(user), PASSWORD, "new@example.org", CTX
    )
    good = auth_world.email.last_code("new@example.org")

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.confirm_email_change.execute(
            actor_of(user), "000000" if good != "000000" else "111111", CTX
        )

    assert auth_world.user(user.id).recovery_email == user.recovery_email


# - - - Activity and step-up - - -


async def test_activity_lists_own_events_newest_first_with_a_cursor(
    auth_world: World,
) -> None:
    """UF-ID-14, GEN-6: the user's own security log, paginated."""
    user = await auth_world.add_user()
    stranger = await auth_world.add_user(login="x.y", recovery_email="x@example.org")
    for index in range(5):
        auth_world.clock.advance(minutes=1)
        async with auth_world.uow() as uow:
            from app.modules.identity.application.audit_drafts import make_audit

            uow.audit(make_audit(f"test.event{index}", user_id=user.id))
            uow.audit(make_audit("test.other", user_id=stranger.id))
            await uow.commit()

    first = await auth_world.auth.list_activity.execute(
        actor_of(user), cursor=None, limit=3
    )
    second = await auth_world.auth.list_activity.execute(
        actor_of(user), cursor=first.next_cursor, limit=3
    )

    assert [e.type for e in first.items] == [
        "test.event4",
        "test.event3",
        "test.event2",
    ]
    assert [e.type for e in second.items] == ["test.event1", "test.event0"]
    assert second.next_cursor is None


async def test_step_up_sends_a_code_keyed_by_the_user(auth_world: World) -> None:
    """Contract: purpose step-up, subject key = user id, falls back to the email."""
    user = await auth_world.add_user()

    channels = await auth_world.auth.step_up.execute(actor_of(user), CTX)

    assert channels == ["email"]
    code = auth_world.otp.last("step-up").code
    assert await auth_world.auth.otp_store.verify("step-up", str(user.id), code)
