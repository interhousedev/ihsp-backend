"""ID-1, ID-2, ID-3, ID-5, ACA-18: starting a registration with EMIS credentials."""

from dataclasses import replace

from app.modules.identity.application.register_errors import (
    EmisAlreadyLinkedError,
    WrongInstitutionError,
)
from app.shared.base_error import RateLimitedError
from app.shared.contracts.emis import EmisAuthFailed, EmisUnavailable
from app.shared.contracts.identity import UserStatus
from app.shared.ids import hash_token
from tests.identity.emis.fakes import make_account
from tests.identity.emis.world import World

import pytest


async def start(world: World, login: str = "student01", ip: str = "10.0.0.1") -> str:
    started = await world.register_start.execute(
        emis_login=login, emis_password="password", ip=ip, locale="ru"
    )
    return started.registration_token


async def test_start_returns_the_imported_profile_and_the_login(
    world: World,
) -> None:
    """ID-1, ID-5: profile from EMIS and the login the student will get."""
    started = await world.register_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.1", locale="ru"
    )

    assert started.profile.group_name == "2TN2"
    assert started.login == "abdullayev.alisher"
    assert started.imported_match is None
    pending = await world.pending_registrations.get(started.registration_token)
    assert pending is not None
    assert pending.login == "abdullayev.alisher"
    assert len(pending.subjects) == 8


async def test_the_emis_password_is_kept_only_as_ciphertext(world: World) -> None:
    """ID-1: Redis holds Transit ciphertext, never the password."""
    token = await start(world)

    pending = await world.pending_registrations.get(token)

    assert pending is not None
    assert pending.password_enc.startswith("vault:v1:")
    assert await world.store.decrypt(pending.password_enc) == "password"
    stored = await world.redis.get(f"reg:{hash_token(token)}")
    assert stored is not None
    assert '"password"' not in stored
    assert token not in stored


async def test_the_password_is_encrypted_before_emis_is_asked(world: World) -> None:
    """ID-1: encrypt first, so a failure later never leaves plaintext around."""
    world.emis.down = True

    with pytest.raises(EmisUnavailable):
        await start(world)

    assert world.store.calls[0] == "encrypt"
    assert world.emis.calls == ["login"]
    assert await world.redis.keys("reg:*") == []


async def test_wrong_emis_credentials_are_refused_and_count_toward_the_limit(
    world: World,
) -> None:
    """ID-3: a failed login still uses up an attempt."""
    with pytest.raises(EmisAuthFailed):
        await world.register_start.execute(
            emis_login="student01", emis_password="nope", ip="10.0.0.1", locale="ru"
        )

    assert await world.redis.get("rl:reg-ip:10.0.0.1") == "1"
    assert await world.redis.get("rl:reg-global") == "1"


async def test_another_institution_is_refused(world: World) -> None:
    """ID-2: only the lyceum's students may register."""
    token = await world.emis.login("student01", "password")
    profile = await world.emis.profile(token)
    world.emis.profiles["student01"] = replace(profile, institution_id=999)

    with pytest.raises(WrongInstitutionError):
        await start(world)


@pytest.mark.parametrize("status", [UserStatus.ACTIVE, UserStatus.BLOCKED])
async def test_an_emis_profile_can_be_linked_only_once(
    world: World, status: UserStatus
) -> None:
    """ID-3: an active or blocked account already owns the EMIS profile."""
    world.repo.add(make_account(emis_student_id=78201, status=status))

    with pytest.raises(EmisAlreadyLinkedError):
        await start(world)


async def test_a_deleted_account_does_not_block_a_new_registration(
    world: World,
) -> None:
    """ID-29: after deletion the EMIS profile is free again."""
    world.repo.add(
        make_account(emis_student_id=78201, status=UserStatus.DELETED, login="old.one")
    )

    token = await start(world)

    assert token


async def test_an_import_with_the_same_emis_id_needs_no_confirmation(
    world: World,
) -> None:
    """ACA-18: matched by EMIS ID, the import is claimed without asking."""
    imported = world.repo.add(
        make_account(
            login=None,
            status=UserStatus.UNREGISTERED,
            email=None,
            password=None,
            emis_student_id=78201,
            first_name="Alisher",
            last_name="Abdullayev",
        )
    )

    started = await world.register_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.1", locale="ru"
    )

    assert started.imported_match is not None
    assert started.imported_match.needs_confirmation is False
    pending = await world.pending_registrations.get(started.registration_token)
    assert pending is not None
    assert pending.import_user_id == imported.id
    assert started.login == "abdullayev.alisher"


async def test_an_import_found_by_name_asks_the_student_to_confirm(
    world: World,
) -> None:
    """ACA-18: matched by name and group, the student answers "Is this you?"."""
    imported = world.repo.add(
        make_account(
            login=None,
            status=UserStatus.UNREGISTERED,
            email=None,
            password=None,
            emis_student_id=None,
            first_name="Alisher",
            last_name="Abdullayev",
        )
    )
    world.enrollment.imported = imported.id

    started = await world.register_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.1", locale="ru"
    )

    assert started.imported_match is not None
    assert started.imported_match.needs_confirmation is True
    assert started.imported_match.group_name == "2TN2"


async def test_a_name_match_that_belongs_to_another_emis_id_is_ignored(
    world: World,
) -> None:
    """ACA-18: an import that already has a different EMIS ID is somebody else."""
    other = world.repo.add(
        make_account(
            login=None,
            status=UserStatus.UNREGISTERED,
            email=None,
            password=None,
            emis_student_id=99999,
        )
    )
    world.enrollment.imported = other.id

    started = await world.register_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.1", locale="ru"
    )

    assert started.imported_match is None


async def test_a_taken_login_gets_a_number(world: World) -> None:
    """ID-5: brastilov.aleksey, then brastilov.aleksey2."""
    world.repo.add(make_account(login="abdullayev.alisher", emis_student_id=1))

    started = await world.register_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.1", locale="ru"
    )

    assert started.login == "abdullayev.alisher2"


async def test_the_eleventh_attempt_from_one_ip_is_rate_limited(world: World) -> None:
    """ID-3: 10 attempts per hour per IP."""
    for _ in range(10):
        with pytest.raises(EmisAuthFailed):
            await world.register_start.execute(
                emis_login="student01", emis_password="x", ip="10.0.0.1", locale="ru"
            )

    with pytest.raises(RateLimitedError) as caught:
        await start(world)

    assert caught.value.status == 429
    assert caught.value.params["retry_after"] >= 1


async def test_another_ip_is_not_limited_by_the_first(world: World) -> None:
    """ID-3: the per-IP counter is per IP."""
    for _ in range(10):
        with pytest.raises(EmisAuthFailed):
            await world.register_start.execute(
                emis_login="student01", emis_password="x", ip="10.0.0.1", locale="ru"
            )

    assert await start(world, ip="10.0.0.2")


async def test_the_global_limit_applies_to_every_ip(world: World) -> None:
    """ID-3: 300 attempts per hour overall."""
    await world.redis.set("rl:reg-global", 300)

    with pytest.raises(RateLimitedError):
        await start(world, ip="10.9.9.9")
