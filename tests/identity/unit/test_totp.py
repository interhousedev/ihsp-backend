"""The authenticator app (TOTP): enable, log in, recovery codes, reuse, disable."""

from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import OtpInvalidError, TotpStateError
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from tests.identity.support import PASSWORD, World, sign_init_data

import pyotp
import pytest

CTX = RequestContext(ip="203.0.113.5", user_agent="pytest")


def actor_of(user: User) -> Actor:
    """The signed-in user."""
    return Actor(user_id=user.id, roles=frozenset(user.roles))


def code_at(world: World, secret: str, offset_steps: int = 0) -> str:
    """The code of the fake clock's step (plus an offset)."""
    moment = world.clock.now().timestamp() + offset_steps * 30
    return pyotp.TOTP(secret).at(int(moment))


def tg_init(world: World) -> str:
    """Fresh signed initData of Telegram account 555."""
    return sign_init_data(telegram_id=555, auth_date=int(world.clock.now().timestamp()))


async def enable(world: World, user: User) -> tuple[str, list[str]]:
    """Set the app up; return the secret and the recovery codes."""
    setup = await world.auth.factors.manage_totp.start(actor_of(user))
    codes = await world.auth.factors.manage_totp.confirm(
        actor_of(user), code_at(world, setup.secret), CTX
    )
    return setup.secret, codes


async def log_in_password(world: World, user: User, challenge: str = "lc-1"):
    """The first factor."""
    return await world.auth.log_in_with_password.execute(
        challenge, user.login or "", PASSWORD, remember=False, ctx=CTX
    )


async def test_setup_gives_an_otpauth_uri_and_stores_the_secret_encrypted(
    auth_world: World,
) -> None:
    """Issuer IHT ID, account = login; the stored secret is a Transit ciphertext."""
    user = await auth_world.add_user()
    setup = await auth_world.auth.factors.manage_totp.start(actor_of(user))

    assert setup.otpauth_uri.startswith("otpauth://totp/IHT%20ID:")
    assert "issuer=IHT%20ID" in setup.otpauth_uri
    assert (user.login or "") in setup.otpauth_uri

    codes = await auth_world.auth.factors.manage_totp.confirm(
        actor_of(user), code_at(auth_world, setup.secret), CTX
    )
    assert len(codes) == 10 and len(set(codes)) == 10
    stored = auth_world.store.factors[user.id]
    assert stored.totp_enabled
    assert stored.totp_secret_enc and stored.totp_secret_enc.startswith("vault:v1:")
    assert setup.secret not in stored.totp_secret_enc
    assert codes[0] not in stored.recovery_code_hashes
    assert "totp.enabled" in auth_world.store.audit_types(user.id)


async def test_a_wrong_first_code_does_not_enable(auth_world: World) -> None:
    """Confirmation needs the right code."""
    user = await auth_world.add_user()
    setup = await auth_world.auth.factors.manage_totp.start(actor_of(user))
    wrong = "000000" if code_at(auth_world, setup.secret) != "000000" else "111111"

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.factors.manage_totp.confirm(actor_of(user), wrong, CTX)
    assert user.id not in auth_world.store.factors


async def test_login_asks_for_the_code_then_accepts_it(auth_world: World) -> None:
    """Password first; the ticket's method is totp; amr pwd+otp, mfa."""
    user = await auth_world.add_user()
    secret, _ = await enable(auth_world, user)
    auth_world.clock.advance(seconds=60)
    auth_world.hydra.add_login("lc-1")

    first = await log_in_password(auth_world, user)
    assert first.redirect_to is None
    assert first.second_factor and first.second_factor.method == "totp"

    result = await auth_world.auth.factors.log_in_with_totp.execute(
        "lc-1", first.second_factor.ticket, code_at(auth_world, secret), ctx=CTX
    )
    assert result.redirect_to
    assert auth_world.hydra.last("accept_login")["amr"] == ["pwd", "otp"]


async def test_previous_step_is_accepted_but_a_code_never_twice(
    auth_world: World,
) -> None:
    """±1 step of drift; a replayed code is refused."""
    user = await auth_world.add_user()
    secret, _ = await enable(auth_world, user)
    auth_world.clock.advance(seconds=300)
    auth_world.hydra.add_login("lc-1")
    auth_world.hydra.add_login("lc-2")
    old = code_at(auth_world, secret, -1)

    first = await log_in_password(auth_world, user, "lc-1")
    assert first.second_factor
    await auth_world.auth.factors.log_in_with_totp.execute(
        "lc-1", first.second_factor.ticket, old, ctx=CTX
    )

    second = await log_in_password(auth_world, user, "lc-2")
    assert second.second_factor
    with pytest.raises(OtpInvalidError):
        await auth_world.auth.factors.log_in_with_totp.execute(
            "lc-2", second.second_factor.ticket, old, ctx=CTX
        )


async def test_a_code_two_steps_old_is_refused(auth_world: World) -> None:
    """Only one step either side."""
    user = await auth_world.add_user()
    secret, _ = await enable(auth_world, user)
    auth_world.clock.advance(seconds=300)
    auth_world.hydra.add_login("lc-1")
    first = await log_in_password(auth_world, user)
    assert first.second_factor

    with pytest.raises(OtpInvalidError):
        await auth_world.auth.factors.log_in_with_totp.execute(
            "lc-1", first.second_factor.ticket, code_at(auth_world, secret, -2), ctx=CTX
        )


async def test_recovery_code_works_once(auth_world: World) -> None:
    """A recovery code signs in and is then gone."""
    user = await auth_world.add_user()
    _, codes = await enable(auth_world, user)
    auth_world.hydra.add_login("lc-1")
    auth_world.hydra.add_login("lc-2")

    first = await log_in_password(auth_world, user, "lc-1")
    assert first.second_factor
    result = await auth_world.auth.factors.log_in_with_totp.execute(
        "lc-1", first.second_factor.ticket, codes[3].upper(), ctx=CTX
    )
    assert result.redirect_to
    assert len(auth_world.store.factors[user.id].recovery_code_hashes) == 9

    second = await log_in_password(auth_world, user, "lc-2")
    assert second.second_factor
    with pytest.raises(OtpInvalidError):
        await auth_world.auth.factors.log_in_with_totp.execute(
            "lc-2", second.second_factor.ticket, codes[3], ctx=CTX
        )


async def test_five_wrong_codes_burn_the_ticket(auth_world: World) -> None:
    """Attempts are counted on the ticket."""
    user = await auth_world.add_user()
    secret, _ = await enable(auth_world, user)
    auth_world.clock.advance(seconds=120)
    auth_world.hydra.add_login("lc-1")
    first = await log_in_password(auth_world, user)
    assert first.second_factor
    good = code_at(auth_world, secret)
    wrong = "000000" if good != "000000" else "111111"

    for left in (4, 3, 2, 1, 0):
        with pytest.raises(OtpInvalidError) as caught:
            await auth_world.auth.factors.log_in_with_totp.execute(
                "lc-1", first.second_factor.ticket, wrong, ctx=CTX
            )
        assert caught.value.params == {"attempts_left": left}
    with pytest.raises(OtpInvalidError):
        await auth_world.auth.factors.log_in_with_totp.execute(
            "lc-1", first.second_factor.ticket, good, ctx=CTX
        )


async def test_totp_replaces_the_sent_code_for_administration(
    auth_world: World,
) -> None:
    """An admin with OTP and TOTP gets the app, and no code is sent."""
    admin = await auth_world.add_user(
        roles={Role.ADMIN}, otp_enabled=True, otp_via_email=True
    )
    await enable(auth_world, admin)
    auth_world.hydra.add_login("lc-1", client_id="admin")

    first = await log_in_password(auth_world, admin)

    assert first.second_factor and first.second_factor.method == "totp"
    assert auth_world.otp.codes == []


async def test_disable_needs_a_fresh_code(auth_world: World) -> None:
    """A wrong code keeps the app; a right one removes secret and codes."""
    user = await auth_world.add_user()
    secret, _ = await enable(auth_world, user)
    auth_world.clock.advance(seconds=60)
    manage = auth_world.auth.factors.manage_totp

    with pytest.raises(OtpInvalidError):
        await manage.disable(actor_of(user), "12345678", CTX)
    await manage.disable(actor_of(user), code_at(auth_world, secret), CTX)

    factors = auth_world.store.factors[user.id]
    assert not factors.totp_enabled and factors.recovery_code_hashes == []
    with pytest.raises(TotpStateError):
        await manage.disable(actor_of(user), code_at(auth_world, secret), CTX)


async def test_admin_otp_reset_also_removes_the_app(auth_world: World) -> None:
    """A lost phone: the administrator's reset clears TOTP too."""
    admin = await auth_world.add_user(roles={Role.ADMIN})
    user = await auth_world.add_user(login="lost.phone")
    await enable(auth_world, user)

    await auth_world.auth.admin_reset_otp.execute(actor_of(admin), user.id, CTX)

    assert not auth_world.store.factors[user.id].totp_enabled


async def test_telegram_link_with_password_also_asks_for_the_app(
    auth_world: World,
) -> None:
    """The mini app login cannot skip the authenticator app."""
    user = await auth_world.add_user()
    secret, _ = await enable(auth_world, user)
    auth_world.clock.advance(seconds=60)
    login = auth_world.auth.telegram_login

    first = await login.execute(
        tg_init(auth_world), user.login or "", password=PASSWORD, otp_code=None, ctx=CTX
    )
    assert not first.linked and first.second_factor_result
    assert first.second_factor_result.second_factor
    assert first.second_factor_result.second_factor.method == "totp"

    done = await login.execute(
        tg_init(auth_world),
        user.login or "",
        password=PASSWORD,
        otp_code=code_at(auth_world, secret),
        ctx=CTX,
    )
    assert done.linked
