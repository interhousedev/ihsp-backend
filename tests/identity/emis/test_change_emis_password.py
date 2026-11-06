"""Changing the password in EMIS: both factors are checked before EMIS is changed."""

from uuid import UUID

from app.modules.identity.application.change_emis_password import EmisPasswordChange
from app.modules.identity.application.register_errors import (
    EmisNewPasswordRejectedError,
    OtpCodeInvalidError,
    WrongEmisPasswordError,
    WrongPasswordError,
)
from app.modules.identity.infrastructure.emis.fake import FAKE_PASSWORD
from app.shared.actor import Actor, Role
from app.shared.contracts.emis import EmisUnavailable
from tests.identity.emis.world import World

import pytest

NEW = "new-emis-password"


def student(user_id: UUID) -> Actor:
    return Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))


async def registered_student(world: World) -> tuple[Actor, str]:
    """Return a student and a valid account password check value."""
    _, registered = await world.register()
    account = world.repo.accounts[registered.user_id]
    account.password_hash = "hash:account-password"
    world.emis.calls.clear()
    world.kicker.calls.clear()
    return student(registered.user_id), "account-password"


@pytest.fixture(autouse=True)
def _plain_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    async def verify(self: object, password_hash: str, password: str) -> bool:
        return password_hash == f"hash:{password}"

    monkeypatch.setattr("tests.identity.emis.fakes.PlainHasher.verify", verify)


async def test_a_change_with_the_account_password_updates_emis_and_the_secret(
    world: World,
) -> None:
    actor, password = await registered_student(world)
    ref = world.secret_ref_of(actor.user_id)

    await world.change_emis_password.execute(
        actor,
        EmisPasswordChange(FAKE_PASSWORD, NEW, account_password=password),
    )

    assert world.emis.passwords["student01"] == NEW
    secret = world.store.secrets[ref]
    assert await world.store.decrypt(secret.password_enc) == NEW
    assert world.kicker.calls == [
        ("academic.sync_student", {"user_id": str(actor.user_id)})
    ]


async def test_a_change_with_a_step_up_code_succeeds(world: World) -> None:
    actor, _ = await registered_student(world)
    code = await world.otp.issue("step-up", str(actor.user_id))

    await world.change_emis_password.execute(
        actor, EmisPasswordChange(FAKE_PASSWORD, NEW, otp_code=code)
    )

    assert world.emis.passwords["student01"] == NEW


async def test_a_wrong_account_password_never_reaches_emis(world: World) -> None:
    actor, _ = await registered_student(world)

    with pytest.raises(WrongPasswordError):
        await world.change_emis_password.execute(
            actor, EmisPasswordChange(FAKE_PASSWORD, NEW, account_password="nope")
        )

    assert world.emis.calls == []


async def test_a_wrong_code_never_reaches_emis(world: World) -> None:
    actor, _ = await registered_student(world)

    with pytest.raises(OtpCodeInvalidError):
        await world.change_emis_password.execute(
            actor, EmisPasswordChange(FAKE_PASSWORD, NEW, otp_code="000000")
        )

    assert world.emis.calls == []


async def test_a_wrong_current_emis_password_changes_nothing(world: World) -> None:
    actor, password = await registered_student(world)

    with pytest.raises(WrongEmisPasswordError):
        await world.change_emis_password.execute(
            actor, EmisPasswordChange("nope", NEW, account_password=password)
        )

    assert "change_password" not in world.emis.calls


async def test_a_refused_new_password_keeps_the_secret(world: World) -> None:
    actor, password = await registered_student(world)
    ref = world.secret_ref_of(actor.user_id)

    with pytest.raises(EmisNewPasswordRejectedError):
        await world.change_emis_password.execute(
            actor, EmisPasswordChange(FAKE_PASSWORD, "weak", account_password=password)
        )

    secret = world.store.secrets[ref]
    assert await world.store.decrypt(secret.password_enc) == FAKE_PASSWORD


async def test_an_emis_outage_is_a_503(world: World) -> None:
    actor, password = await registered_student(world)
    world.emis.down = True

    with pytest.raises(EmisUnavailable):
        await world.change_emis_password.execute(
            actor, EmisPasswordChange(FAKE_PASSWORD, NEW, account_password=password)
        )
