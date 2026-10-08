"""ID-8, UF-ID-12: replacing the EMIS password after EMIS rejected the old one."""

from dataclasses import replace
from uuid import UUID

from app.modules.identity.application.register_errors import (
    EmisProfileMismatchError,
    NoEmisLinkError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError, RateLimitedError
from app.shared.contracts.emis import EmisAuthFailed, EmisUnavailable
from tests.identity.emis.fakes import make_account
from tests.identity.emis.world import World

import pytest


def student(user_id: UUID) -> Actor:
    return Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))


async def needs_reauth_student(world: World) -> Actor:
    _, registered = await world.register()
    world.repo.accounts[registered.user_id].emis_status = "needs_reauth"
    world.emis.passwords["student01"] = "new-emis-password"
    world.kicker.calls.clear()
    return student(registered.user_id)


async def test_the_new_password_replaces_the_secret_and_reactivates_the_link(
    world: World,
) -> None:
    """ID-8: checked against EMIS first, then stored; a sync is queued."""
    actor = await needs_reauth_student(world)
    ref = world.secret_ref_of(actor.user_id)

    result = await world.update_emis_password.execute(
        actor, emis_password="new-emis-password"
    )

    assert result == "active"
    assert world.repo.accounts[actor.user_id].emis_status == "active"
    secret = world.store.secrets[ref]
    assert await world.store.decrypt(secret.password_enc) == "new-emis-password"
    assert secret.login == "student01"
    assert world.store.replaced == [ref]
    assert world.kicker.calls == [
        ("academic.sync_student", {"user_id": str(actor.user_id)})
    ]
    assert world.ledger.audits[-1].type == "emis.password_updated"


async def test_a_wrong_password_leaves_vault_and_status_untouched(
    world: World,
) -> None:
    """UF-ID-12 3a: Vault is not changed."""
    actor = await needs_reauth_student(world)

    with pytest.raises(EmisAuthFailed):
        await world.update_emis_password.execute(actor, emis_password="still-wrong")

    assert world.store.replaced == []
    assert world.repo.accounts[actor.user_id].emis_status == "needs_reauth"
    assert world.kicker.calls == []


async def test_credentials_of_another_emis_profile_are_refused(world: World) -> None:
    """UF-ID-12 3b: the EMIS profile must be the linked one."""
    actor = await needs_reauth_student(world)
    token = await world.emis.login("student01", "new-emis-password")
    profile = await world.emis.profile(token)
    world.emis.profiles["student01"] = replace(profile, emis_student_id=1)

    with pytest.raises(EmisProfileMismatchError):
        await world.update_emis_password.execute(
            actor, emis_password="new-emis-password"
        )

    assert world.store.replaced == []


async def test_a_student_without_an_emis_link_cannot_update(world: World) -> None:
    """ID-8: nothing to update."""
    account = world.repo.add(make_account(emis_student_id=None, vault_ref=None))

    with pytest.raises(NoEmisLinkError):
        await world.update_emis_password.execute(student(account.id), emis_password="x")


async def test_only_students_may_update_an_emis_password(world: World) -> None:
    """ID-8: staff have no EMIS link."""
    actor = Actor(user_id=make_account().id, roles=frozenset({Role.TEACHER}))

    with pytest.raises(ForbiddenError):
        await world.update_emis_password.execute(actor, emis_password="x")


async def test_an_emis_outage_is_reported_as_unavailable(world: World) -> None:
    """ID-7: EMIS down is not a wrong password."""
    actor = await needs_reauth_student(world)
    world.emis.down = True

    with pytest.raises(EmisUnavailable):
        await world.update_emis_password.execute(
            actor, emis_password="new-emis-password"
        )


async def test_attempts_are_limited_per_user(world: World) -> None:
    """ID-8: the endpoint must not be a password-guessing oracle."""
    actor = await needs_reauth_student(world)
    for _ in range(10):
        with pytest.raises(EmisAuthFailed):
            await world.update_emis_password.execute(actor, emis_password="guess")

    with pytest.raises(RateLimitedError):
        await world.update_emis_password.execute(actor, emis_password="guess")
