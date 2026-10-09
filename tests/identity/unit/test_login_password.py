"""ID-12, ID-15, ID-16, ID-11: password login and the Administration second factor."""

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import (
    AccountLockedError,
    ChallengeUsedError,
    InvalidCredentialsError,
    OtpInvalidError,
    RoleMissingError,
)
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from tests.identity.support import PASSWORD, World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest/1.0")


async def log_in(world: World, login: str, password: str, challenge: str = "lc-1"):
    """Run the password login use case."""
    return await world.auth.log_in_with_password.execute(
        challenge, login, password, remember=True, ctx=CTX
    )


async def test_correct_password_accepts_the_hydra_login_and_creates_a_session(
    auth_world: World,
) -> None:
    """ID-12, ID-16: amr pwd, a Session row linked to the Hydra session."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1", client_id="sp")

    result = await log_in(auth_world, user.login or "", PASSWORD)

    assert result.redirect_to == "https://hydra/continue?login_verifier=lc-1"
    accepted = auth_world.hydra.last("accept_login")
    assert accepted["subject"] == str(user.id)
    assert accepted["amr"] == ["pwd"]
    assert accepted["remember"] is True
    (session,) = auth_world.store.sessions.values()
    assert session.hydra_sid == "hydra-sid-lc-1"
    assert session.amr == ["pwd"]
    assert accepted["context"]["session_id"] == str(session.id)
    assert "login.success" in auth_world.store.audit_types(user.id)
    assert auth_world.user(user.id).last_login_at == auth_world.clock.now()


async def test_login_is_case_insensitive(auth_world: World) -> None:
    """ID-12: logins are matched without regard to case."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")

    result = await log_in(auth_world, (user.login or "").upper(), PASSWORD)

    assert result.redirect_to


async def test_wrong_password_is_refused_and_audited(auth_world: World) -> None:
    """ID-15: a generic error, an audit event, no session."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")

    with pytest.raises(InvalidCredentialsError):
        await log_in(auth_world, user.login or "", "Wr0ngPassword")

    assert auth_world.store.sessions == {}
    assert auth_world.store.audit_types(user.id) == ["login.failed"]


async def test_unknown_login_gets_the_same_error(auth_world: World) -> None:
    """ID-15: the answer does not reveal whether the login exists."""
    auth_world.hydra.add_login("lc-1")

    with pytest.raises(InvalidCredentialsError) as caught:
        await log_in(auth_world, "nobody.here", PASSWORD)

    assert caught.value.params == {}
    assert auth_world.store.audits == []


async def test_blocked_user_cannot_log_in_even_with_the_right_password(
    auth_world: World,
) -> None:
    """GEN-5: a blocked account is refused with a 401 after the password check."""
    user = await auth_world.add_user(status=UserStatus.BLOCKED)
    auth_world.hydra.add_login("lc-1")

    with pytest.raises(InvalidCredentialsError) as caught:
        await log_in(auth_world, user.login or "", PASSWORD)

    assert caught.value.status == 401
    assert auth_world.store.sessions == {}


async def test_teacher_is_refused_by_the_admin_client(auth_world: World) -> None:
    """ID-16: the admin client requires the Administration role."""
    teacher = await auth_world.add_user(roles={Role.TEACHER})
    auth_world.hydra.add_login("lc-1", client_id="admin")

    with pytest.raises(RoleMissingError):
        await log_in(auth_world, teacher.login or "", PASSWORD)


async def test_student_is_refused_by_the_staff_client(auth_world: World) -> None:
    """ID-16: the staff client requires the teacher role."""
    student = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1", client_id="staff")

    with pytest.raises(RoleMissingError):
        await log_in(auth_world, student.login or "", PASSWORD)


async def test_administration_without_otp_logs_in_with_the_password_alone(
    auth_world: World,
) -> None:
    """OTP is optional: an administrator who did not turn it on gets no code step."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=False)
    auth_world.hydra.add_login("lc-1", client_id="admin")

    result = await log_in(auth_world, admin.login or "", PASSWORD)

    assert result.second_factor is None
    assert result.redirect_to
    assert auth_world.hydra.last("accept_login")["amr"] == ["pwd"]


async def test_administration_gets_a_second_factor_then_logs_in_with_pwd_and_otp(
    auth_world: World,
) -> None:
    """ID-11: password first, then a code; amr [pwd, otp] and mfa_at are recorded."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    auth_world.hydra.add_login("lc-1", client_id="admin")

    first = await log_in(auth_world, admin.login or "", PASSWORD)

    assert first.redirect_to is None
    assert first.second_factor is not None
    assert auth_world.hydra.names() == []
    sent = auth_world.otp.last("login2fa")
    assert sent.channels == ("email",)

    result = await auth_world.auth.log_in_with_otp.execute(
        "lc-1",
        admin.login or "",
        sent.code,
        ticket=first.second_factor.ticket,
        ctx=CTX,
    )

    assert result.redirect_to
    accepted = auth_world.hydra.last("accept_login")
    assert accepted["amr"] == ["pwd", "otp"]
    (session,) = auth_world.store.sessions.values()
    assert session.mfa_at == auth_world.clock.now()
    assert accepted["context"]["mfa_at"] == auth_world.clock.now().isoformat()


async def test_administration_needs_the_second_factor_on_every_platform(
    auth_world: World,
) -> None:
    """ID-11: an admin logging in to sp is also asked for the code."""
    admin = await auth_world.add_user(
        roles={Role.ADMIN, Role.STUDENT}, otp_enabled=True
    )
    auth_world.hydra.add_login("lc-1", client_id="sp")

    result = await log_in(auth_world, admin.login or "", PASSWORD)

    assert result.second_factor is not None


async def test_wrong_second_factor_code_is_refused_and_shows_attempts_left(
    auth_world: World,
) -> None:
    """ID-14: a wrong code reports the attempts left."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    auth_world.hydra.add_login("lc-1", client_id="admin")
    first = await log_in(auth_world, admin.login or "", PASSWORD)
    assert first.second_factor is not None

    with pytest.raises(OtpInvalidError) as caught:
        await auth_world.auth.log_in_with_otp.execute(
            "lc-1",
            admin.login or "",
            "000000" if auth_world.otp.last().code != "000000" else "111111",
            ticket=first.second_factor.ticket,
            ctx=CTX,
        )

    assert caught.value.params == {"attempts_left": 2}
    assert auth_world.store.sessions == {}


async def test_five_failures_lock_the_login_for_this_ip(auth_world: World) -> None:
    """ID-15: failures back off per login and IP, so the owner is not locked out."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await log_in(auth_world, user.login or "", "Wr0ngPassword")

    with pytest.raises(AccountLockedError) as caught:
        await log_in(auth_world, user.login or "", PASSWORD)

    assert caught.value.params["retry_after"] == 60
    other_ip = RequestContext(ip="198.51.100.7", user_agent="pytest")
    result = await auth_world.auth.log_in_with_password.execute(
        "lc-1", user.login or "", PASSWORD, remember=False, ctx=other_ip
    )
    assert result.redirect_to


async def test_repeated_failures_notify_the_user_once_per_hour(
    auth_world: World,
) -> None:
    """ID-15: after five failures the user gets a login_failures notification."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await log_in(auth_world, user.login or "", "Wr0ngPassword")

    assert auth_world.store.notification_types() == ["login_failures"]
    draft = auth_world.store.notifications[0]
    assert draft.payload == {"count": 5, "ip": "203.0.113.5"}
    assert draft.dedupe_key.startswith(f"login-failures:{user.id}:")


async def test_a_challenge_hydra_already_handled_is_reported_with_its_redirect(
    auth_world: World,
) -> None:
    """The web follows redirect_to of auth/challenge-used (410)."""
    user = await auth_world.add_user()
    auth_world.hydra.add_login("lc-1")
    auth_world.hydra.used.add("lc-1")

    with pytest.raises(ChallengeUsedError) as caught:
        await log_in(auth_world, user.login or "", PASSWORD)

    assert caught.value.status == 410
    assert caught.value.params["redirect_to"] == "https://hydra/restart"
