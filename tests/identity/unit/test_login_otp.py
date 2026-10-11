"""ID-13, ID-14, ID-15: passwordless login with one-time codes."""

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpInvalidError
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


async def request_code(world: World, login: str, ctx: RequestContext = CTX) -> None:
    """Ask for a login code."""
    await world.auth.request_login_otp.execute(login, ctx)


async def submit(world: World, login: str, code: str, challenge: str = "lc-1"):
    """Finish the passwordless login."""
    return await world.auth.log_in_with_otp.execute(
        challenge, login, code, ticket=None, ctx=CTX
    )


async def test_request_for_an_unknown_login_succeeds_and_sends_nothing(
    auth_world: World,
) -> None:
    """ID-13: the answer never reveals whether OTP is enabled."""
    await request_code(auth_world, "nobody.here")

    assert auth_world.otp.codes == []


async def test_request_sends_a_code_to_every_channel_of_an_otp_account(
    auth_world: World,
) -> None:
    """UF-ID-03: Telegram with delivery on, plus email if chosen."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.add_link(user)

    await request_code(auth_world, user.login or "")

    assert auth_world.otp.last("login").channels == ("telegram", "email")


async def test_account_without_otp_gets_no_code(auth_world: World) -> None:
    """ID-13: silent for accounts that have not enabled OTP."""
    user = await auth_world.add_user(otp_enabled=False)

    await request_code(auth_world, user.login or "")

    assert auth_world.otp.codes == []


async def test_passwordless_login_with_the_right_code(auth_world: World) -> None:
    """UF-ID-03: the session has amr [otp]."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.hydra.add_login("lc-1")
    await request_code(auth_world, user.login or "")

    result = await submit(auth_world, user.login or "", auth_world.otp.last().code)

    assert result.redirect_to
    assert auth_world.hydra.last("accept_login")["amr"] == ["otp"]
    (session,) = auth_world.store.sessions.values()
    assert session.mfa_at is None


async def test_three_wrong_codes_invalidate_the_code(auth_world: World) -> None:
    """ID-14: at most 3 attempts, then the real code no longer works."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.hydra.add_login("lc-1")
    await request_code(auth_world, user.login or "")
    good = auth_world.otp.last().code
    wrong = "000000" if good != "000000" else "111111"

    for left in (2, 1, 0):
        with pytest.raises(OtpInvalidError) as caught:
            await submit(auth_world, user.login or "", wrong)
        assert caught.value.params == {"attempts_left": left}

    with pytest.raises(OtpInvalidError):
        await submit(auth_world, user.login or "", good)


async def test_a_new_code_cannot_be_requested_within_60_seconds(
    auth_world: World,
) -> None:
    """ID-14: the resend cooldown; the request itself stays silent."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)

    await request_code(auth_world, user.login or "")
    await request_code(auth_world, user.login or "")
    assert auth_world.otp.count("login") == 1

    auth_world.clock.advance(seconds=61)
    await auth_world.redis.delete(f"otp:cooldown:login:{user.id}")
    await request_code(auth_world, user.login or "")
    assert auth_world.otp.count("login") == 2


async def test_five_codes_an_hour_then_silence(auth_world: World) -> None:
    """ID-15: 5 codes per hour per account and IP; later requests do nothing."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    for _ in range(7):
        await auth_world.redis.delete(f"otp:cooldown:login:{user.id}")
        await request_code(auth_world, user.login or "")

    assert auth_world.otp.count("login") == 5
    assert set(auth_world.store.notification_types()) == {"login_failures"}
    keys = {n.dedupe_key for n in auth_world.store.notifications}
    assert len(keys) == 1  # one notice per hour: the outbox drops duplicates


async def test_administration_cannot_use_passwordless_otp(auth_world: World) -> None:
    """ID-11: the code is only sent after a correct password."""
    admin = await auth_world.add_user(roles={Role.ADMIN}, otp_enabled=True)
    auth_world.hydra.add_login("lc-1")

    await request_code(auth_world, admin.login or "")
    assert auth_world.otp.codes == []

    with pytest.raises(OtpInvalidError):
        await submit(auth_world, admin.login or "", "123456")


async def test_ten_failed_codes_a_day_block_further_attempts(
    auth_world: World,
) -> None:
    """ID-15: after 10 failures the IP is blocked from passwordless OTP."""
    user = await auth_world.add_user(otp_enabled=True, otp_via_email=True)
    auth_world.hydra.add_login("lc-1")
    for _ in range(10):
        await auth_world.redis.delete(f"otp:cooldown:login:{user.id}")
        await auth_world.redis.delete(f"rl:otp:{user.id}:203.0.113.5")
        await request_code(auth_world, user.login or "")
        with pytest.raises(OtpInvalidError):
            await submit(auth_world, user.login or "", "xxxxxx")

    with pytest.raises(RateLimitedError):
        await submit(auth_world, user.login or "", "123456")
    await request_code(auth_world, user.login or "")
    assert auth_world.otp.count("login") == 10


async def test_unknown_login_gets_the_same_attempts_left_as_a_real_one(
    auth_world: World,
) -> None:
    """Review 2026-10-11: attempts_left must not reveal whether the account exists."""
    auth_world.hydra.add_login("lc-1")

    for left in (2, 1, 0):
        with pytest.raises(OtpInvalidError) as caught:
            await submit(auth_world, "nobody.here", "000000")
        assert caught.value.params == {"attempts_left": left}


async def test_the_code_endpoint_is_limited_per_ip(auth_world: World) -> None:
    """Review 2026-10-11: 300 code submissions per hour per IP."""
    auth_world.hydra.add_login("lc-1")
    await auth_world.redis.set("rl:login-otp-ip:203.0.113.5", "300")
    await auth_world.redis.expire("rl:login-otp-ip:203.0.113.5", 3600)

    with pytest.raises(RateLimitedError):
        await submit(auth_world, "nobody.here", "000000")
