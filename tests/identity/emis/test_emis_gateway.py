"""ID-7, ID-8, SYNC-8: the gateway reuses the token, re-logs in once, flags reauth."""

from datetime import date
from uuid import UUID

from app.modules.identity.application.emis_gateway import EmisGatewayImpl
from app.modules.identity.infrastructure.emis.fake import FakeEmisClient
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCredentialsMissing,
    EmisUnavailable,
)
from app.shared.ids import new_id
from tests.fakes.identity.vault import InMemoryCredentialStore
from tests.identity.emis.fakes import FakeEmisUnitOfWork
from tests.identity.emis.world import World

import pytest


async def registered_user(world: World) -> UUID:
    _, registered = await world.register()
    world.emis.calls.clear()
    return registered.user_id


async def test_profile_uses_the_stored_token_without_logging_in(
    world: World,
) -> None:
    """ID-7: the stored access token is reused."""
    user_id = await registered_user(world)

    profile = await world.gateway.profile(user_id)

    assert profile.emis_student_id == 78201
    assert world.emis.calls == ["profile"]


async def test_subjects_and_ratings_are_passed_through(world: World) -> None:
    """SYNC-2: subjects and one subject's ratings come back normalized."""
    user_id = await registered_user(world)

    subjects = await world.gateway.subjects(user_id)
    ratings = await world.gateway.ratings(user_id, subjects[0].emis_subject_id, 3)

    assert len(subjects) == 8
    assert (ratings.emis_subject_id, ratings.semester) == (101, 3)
    assert ratings.marks


async def test_curriculum_is_passed_through_with_the_stored_token(
    world: World,
) -> None:
    """SYNC-3: the whole curriculum comes back normalized, no login needed."""
    user_id = await registered_user(world)

    curriculum = await world.gateway.curriculum(user_id)

    assert curriculum.emis_id == 2124
    assert [s.number for s in curriculum.semesters] == [1, 2, 3, 4]
    assert len(curriculum.subjects) == 8
    assert world.emis.calls == ["curriculum_detail"]


async def test_a_stale_token_is_replaced_for_the_curriculum_too(world: World) -> None:
    """ID-7: the same one-time re-login for the curriculum."""
    user_id = await registered_user(world)
    ref = world.secret_ref_of(user_id)
    world.emis.revoke(world.store.secrets[ref].access_token)

    curriculum = await world.gateway.curriculum(user_id)

    assert len(curriculum.semester_subjects) == 32
    assert world.emis.calls == ["curriculum_detail", "login", "curriculum_detail"]
    assert [r for r, _ in world.store.updated_tokens] == [ref]


async def test_a_curriculum_of_a_link_that_needs_reauth_fails_fast(
    world: World,
) -> None:
    """SYNC-8: no EMIS request when the stored password is known to be wrong."""
    user_id = await registered_user(world)
    world.repo.accounts[user_id].emis_status = "needs_reauth"

    with pytest.raises(EmisAuthFailed):
        await world.gateway.curriculum(user_id)

    assert world.emis.calls == []


async def test_class_hours_and_timetable_use_the_stored_token(world: World) -> None:
    """ACA-1, ACA-4: the bells and the group's timetable go through the gateway."""
    user_id = await registered_user(world)

    hours = await world.gateway.class_hours(user_id)
    items = await world.gateway.timetable(
        user_id, date(2026, 10, 5), date(2026, 10, 11)
    )

    assert [h.pair_number for h in hours] == [0, 1, 2, 3, 4]
    assert items and {i.teacher.emis_id for i in items if i.teacher} >= {9001}
    assert {i.date for i in items} <= {date(2026, 10, d) for d in range(5, 12)}
    assert world.emis.calls == ["class_hours", "timetable"]


async def test_a_stale_token_is_replaced_for_class_hours_too(world: World) -> None:
    """ID-7: the same one-time re-login for every endpoint."""
    user_id = await registered_user(world)
    world.emis.revoke(world.store.secrets[world.secret_ref_of(user_id)].access_token)

    hours = await world.gateway.class_hours(user_id)

    assert len(hours) == 5
    assert world.emis.calls == ["class_hours", "login", "class_hours"]


async def test_a_stale_token_triggers_one_relogin_and_the_new_token_is_stored(
    world: World,
) -> None:
    """ID-7: a 401 on a data endpoint logs in again, stores the token, retries."""
    user_id = await registered_user(world)
    ref = world.secret_ref_of(user_id)
    world.emis.revoke(world.store.secrets[ref].access_token)

    profile = await world.gateway.profile(user_id)

    assert profile.group_name == "2TN2"
    assert world.emis.calls == ["profile", "login", "profile"]
    assert [r for r, _ in world.store.updated_tokens] == [ref]


async def test_rejected_password_sets_needs_reauth_and_raises_auth_failed(
    world: World,
) -> None:
    """ID-8, SYNC-8: EMIS refusing the stored password flags the link."""
    user_id = await registered_user(world)
    world.emis.revoke(world.store.secrets[world.secret_ref_of(user_id)].access_token)
    world.emis.passwords["student01"] = "changed-in-emis"

    with pytest.raises(EmisAuthFailed):
        await world.gateway.profile(user_id)

    assert world.repo.accounts[user_id].emis_status == "needs_reauth"
    assert world.store.updated_tokens == []


async def test_a_link_that_needs_reauth_fails_fast(world: World) -> None:
    """SYNC-8: the student is skipped without any EMIS request."""
    user_id = await registered_user(world)
    world.repo.accounts[user_id].emis_status = "needs_reauth"

    with pytest.raises(EmisAuthFailed):
        await world.gateway.profile(user_id)

    assert world.emis.calls == []


async def test_a_user_without_an_emis_link_is_auth_failed(world: World) -> None:
    """ID-7: unknown users and users without a link cannot be fetched."""
    with pytest.raises(EmisAuthFailed):
        await world.gateway.profile(new_id())


async def test_an_emis_outage_is_unavailable_and_keeps_the_link(
    world: World,
) -> None:
    """SYNC-8: EMIS down means retry next run; nothing is flagged."""
    user_id = await registered_user(world)
    world.emis.down = True

    with pytest.raises(EmisUnavailable):
        await world.gateway.profile(user_id)

    assert world.repo.accounts[user_id].emis_status == "active"


async def test_a_vault_outage_is_unavailable(world: World) -> None:
    """ID-6: Vault problems are ours, not the student's."""
    user_id = await registered_user(world)
    world.store.down = True

    with pytest.raises(EmisUnavailable):
        await world.gateway.profile(user_id)


async def test_a_fresh_token_that_is_refused_is_unavailable_not_reauth(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ID-7: if EMIS refuses a token it just issued, the password is not at fault."""
    user_id = await registered_user(world)
    token = world.store.secrets[world.secret_ref_of(user_id)].access_token
    world.emis.revoke(token)

    async def stubborn_login(login: str, password: str) -> str:
        return token

    monkeypatch.setattr(world.emis, "login", stubborn_login)

    with pytest.raises(EmisUnavailable):
        await world.gateway.profile(user_id)

    assert world.repo.accounts[user_id].emis_status == "active"


async def test_a_missing_vault_secret_is_credentials_missing_not_an_outage(
    world: World,
) -> None:
    """The sync skips such a student; the link itself is not flagged."""
    user_id = await registered_user(world)
    del world.store.secrets[world.secret_ref_of(user_id)]

    with pytest.raises(EmisCredentialsMissing):
        await world.gateway.curriculum(user_id)

    assert world.emis.calls == []
    assert world.repo.accounts[user_id].emis_status == "active"


async def test_a_real_emis_link_without_a_vault_reference_is_auth_failed(
    world: World,
) -> None:
    """Real mode needs the stored secret: no reference, no EMIS request."""
    user_id = await registered_user(world)
    world.repo.accounts[user_id].emis_vault_ref = None

    with pytest.raises(EmisAuthFailed):
        await world.gateway.profile(user_id)

    assert world.emis.calls == []


def fake_gateway(world: World, store: InMemoryCredentialStore) -> EmisGatewayImpl:
    """The gateway as build_emis wires it in EMIS mode fake."""
    fake = FakeEmisClient(world.clock)
    return EmisGatewayImpl(
        emis=fake,
        store=store,
        uow_factory=lambda: FakeEmisUnitOfWork(world.repo, world.ledger),
        fake_tokens=fake,
    )


async def test_fake_emis_answers_without_any_stored_secret(world: World) -> None:
    """EMIS mode fake: the token follows from the EMIS id; Vault is never read."""
    user_id = await registered_user(world)
    store = InMemoryCredentialStore()
    gateway = fake_gateway(world, store)

    profile = await gateway.profile(user_id)
    curriculum = await gateway.curriculum(user_id)

    assert profile.emis_student_id == 78201  # the fake EMIS student01
    assert curriculum.semesters
    assert store.calls == []


async def test_fake_emis_refuses_an_emis_id_it_does_not_know(world: World) -> None:
    """A linked account with an unknown EMIS id cannot be fetched, even in fake mode."""
    user_id = await registered_user(world)
    world.repo.accounts[user_id].emis_student_id = 1

    with pytest.raises(EmisAuthFailed):
        await fake_gateway(world, InMemoryCredentialStore()).profile(user_id)
