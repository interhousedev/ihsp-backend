"""ID-4, ID-14: the email confirmation code of a pending registration."""

from app.modules.identity.application.register_errors import (
    EmailInUseError,
    RegistrationExpiredError,
)
from app.shared.base_error import RateLimitedError
from app.shared.ids import hash_token
from tests.identity.emis.fakes import make_account
from tests.identity.emis.world import World

import pytest


async def start(world: World, login: str = "student01", ip: str = "10.0.0.1") -> str:
    started = await world.register_start.execute(
        emis_login=login, emis_password="password", ip=ip, locale="uz"
    )
    return started.registration_token


async def skip_cooldown(world: World, token: str) -> None:
    await world.redis.delete(f"rl:reg-email-cooldown:{hash_token(token)}")


async def test_a_code_is_mailed_to_the_normalized_address(world: World) -> None:
    """ID-4: the address is stripped and lowercased; the mail uses the page locale."""
    token = await start(world)

    await world.register_email_code.execute(
        registration_token=token, email="  Aleksey@Example.COM "
    )

    to, template, params, locale = world.emails.sent[-1]
    assert (to, template, locale) == ("aleksey@example.com", "otp", "uz")
    assert len(params["code"]) == 6
    pending = await world.pending_registrations.get(token)
    assert pending is not None
    assert pending.email == "aleksey@example.com"


async def test_an_unknown_token_is_gone(world: World) -> None:
    """ID-1: the flow lives 30 minutes."""
    with pytest.raises(RegistrationExpiredError) as caught:
        await world.register_email_code.execute(
            registration_token="x" * 43, email="a@example.com"
        )

    assert caught.value.status == 410


async def test_an_address_of_another_account_is_refused(world: World) -> None:
    """ID-4: the email must not belong to another user (case-insensitive)."""
    world.repo.add(make_account(email="taken@example.com", emis_student_id=1))
    token = await start(world)

    with pytest.raises(EmailInUseError):
        await world.register_email_code.execute(
            registration_token=token, email="TAKEN@example.com"
        )

    assert world.emails.sent == []


async def test_a_second_code_within_a_minute_is_refused(world: World) -> None:
    """ID-14: 60 seconds between codes."""
    token = await start(world)
    await world.register_email_code.execute(
        registration_token=token, email="a@example.com"
    )

    with pytest.raises(RateLimitedError):
        await world.register_email_code.execute(
            registration_token=token, email="a@example.com"
        )


async def test_a_new_code_replaces_the_old_one_and_the_old_email(
    world: World,
) -> None:
    """ID-14: asking again after the cooldown invalidates the previous code."""
    token = await start(world)
    await world.register_email_code.execute(
        registration_token=token, email="first@example.com"
    )
    first_code = world.emails.last_code()
    await skip_cooldown(world, token)

    await world.register_email_code.execute(
        registration_token=token, email="second@example.com"
    )

    pending = await world.pending_registrations.get(token)
    assert pending is not None
    assert pending.email == "second@example.com"
    assert world.emails.last_code() != first_code
    assert not await world.otp.verify("verify_email", hash_token(token), first_code)


async def test_at_most_five_codes_per_registration(world: World) -> None:
    """ID-14: a flow cannot be used to flood an inbox."""
    token = await start(world)
    for _ in range(5):
        await skip_cooldown(world, token)
        await world.register_email_code.execute(
            registration_token=token, email="a@example.com"
        )

    await skip_cooldown(world, token)
    with pytest.raises(RateLimitedError):
        await world.register_email_code.execute(
            registration_token=token, email="a@example.com"
        )


async def test_at_most_five_codes_per_address_per_hour(world: World) -> None:
    """ID-14: one address cannot be flooded through many registrations."""
    for number in range(1, 6):
        token = await start(world, f"student0{number}", ip=f"10.0.0.{number}")
        await world.register_email_code.execute(
            registration_token=token, email="victim@example.com"
        )
    token = await start(world, "student06", ip="10.0.0.6")

    with pytest.raises(RateLimitedError):
        await world.register_email_code.execute(
            registration_token=token, email="victim@example.com"
        )
