"""ACA-1, ID-5, ID-10: teachers named by an EMIS timetable are found or created once."""

from app.shared.actor import Role
from app.shared.contracts.identity import UserRef, UserStatus
from tests.identity.support import World


async def ensure(
    world: World,
    *,
    emis_id: int | None = 9001,
    first: str = "GULNORA",
    last: str = "KALANDAROVA",
    middle: str | None = "AKBAROVNA",
) -> UserRef:
    return await world.auth.commands.ensure_teacher(
        emis_teacher_id=emis_id, first_name=first, last_name=last, middle_name=middle
    )


async def test_a_new_teacher_waits_for_activation_without_an_email(
    auth_world: World,
) -> None:
    """ID-10: a staff account created from EMIS has no email and no password."""
    ref = await ensure(auth_world)

    stored = auth_world.user(ref.id)
    assert stored.status is UserStatus.PENDING_ACTIVATION
    assert stored.roles == {Role.TEACHER}
    assert (stored.first_name, stored.last_name) == ("Gulnora", "Kalandarova")
    assert stored.middle_name == "Akbarovna"
    assert (stored.recovery_email, stored.password_hash) == (None, None)
    assert stored.emis_teacher_id == 9001
    assert "user.created" in auth_world.store.audit_types(ref.id)


async def test_the_login_follows_the_student_rules_and_never_collides(
    auth_world: World,
) -> None:
    """ID-5: surname.name in Latin, a number is appended on collision."""
    first = await ensure(auth_world, emis_id=1)
    twin = await ensure(
        auth_world, emis_id=2, middle="OTHERNOVNA"
    )  # same names, other EMIS id

    assert first.login == "kalandarova.gulnora"
    assert twin.login == "kalandarova.gulnora2"
    assert first.id != twin.id


async def test_the_same_emis_teacher_is_never_created_twice(
    auth_world: World,
) -> None:
    """ACA-1: matching by EMIS teacher id, even if the name is spelled differently."""
    first = await ensure(auth_world)

    again = await ensure(auth_world, first="Gulnora", last="Kalandarov")

    assert again.id == first.id
    teachers = [u for u in auth_world.store.users.values() if Role.TEACHER in u.roles]
    assert len(teachers) == 1


async def test_an_existing_teacher_is_found_by_name_and_linked_to_the_emis_id(
    auth_world: World,
) -> None:
    """ACA-1: Administration created the teacher by hand; EMIS only adds the id."""
    existing = await auth_world.add_user(
        first_name="Gulnora",
        last_name="Kalandarova",
        roles={Role.TEACHER},
        login="kalandarova.gulnora",
    )

    ref = await ensure(auth_world)

    assert ref.id == existing.id
    assert auth_world.user(existing.id).emis_teacher_id == 9001
    assert len(auth_world.store.users) == 1


async def test_names_match_across_cyrillic_and_latin_spellings(
    auth_world: World,
) -> None:
    """ACA-1: a teacher typed in Cyrillic by Administration matches EMIS's Latin."""
    existing = await auth_world.add_user(
        first_name="Гульнора",
        last_name="Каландарова",
        roles={Role.TEACHER},
        login="kalandarova.gulnora",
    )

    ref = await ensure(auth_world, emis_id=None)

    assert ref.id == existing.id


async def test_a_student_or_another_emis_teacher_with_the_same_name_is_not_a_match(
    auth_world: World,
) -> None:
    """ACA-1: only teachers match, and not those linked to a different EMIS id."""
    await auth_world.add_user(
        first_name="Gulnora", last_name="Kalandarova", login="kalandarova.gulnora"
    )  # a student
    other = await ensure(auth_world, emis_id=5)

    ref = await ensure(auth_world, emis_id=6)

    assert ref.id != other.id
    assert auth_world.user(ref.id).emis_teacher_id == 6


async def test_an_ambiguous_name_creates_a_new_account_instead_of_guessing(
    auth_world: World,
) -> None:
    """ACA-1: two teachers with one name and no id to tell them apart."""
    for email in ("a@example.org", "b@example.org"):
        await auth_world.add_user(
            first_name="Gulnora",
            last_name="Kalandarova",
            roles={Role.TEACHER},
            login=f"kalandarova.gulnora.{email[0]}",
            recovery_email=email,
        )

    ref = await ensure(auth_world, emis_id=None, middle=None)

    assert auth_world.user(ref.id).status is UserStatus.PENDING_ACTIVATION
    assert len(auth_world.store.users) == 3


async def test_a_patronymic_tells_two_teachers_with_one_name_apart(
    auth_world: World,
) -> None:
    """ACA-1: the patronymic narrows an ambiguous match."""
    wanted = None
    for middle in ("Akbarovna", "Rustamovna"):
        user = await auth_world.add_user(
            first_name="Gulnora",
            last_name="Kalandarova",
            middle_name=middle,
            roles={Role.TEACHER},
            login=f"kalandarova.gulnora.{middle[0].lower()}",
            recovery_email=f"{middle.lower()}@example.org",
        )
        wanted = user if middle == "Rustamovna" else wanted

    ref = await ensure(auth_world, emis_id=None, middle="RUSTAMOVNA")

    assert wanted is not None and ref.id == wanted.id


async def test_a_deactivated_teacher_is_not_brought_back(auth_world: World) -> None:
    """ACA-7: deactivated teachers are not matched; EMIS names a new account."""
    gone = await auth_world.add_user(
        first_name="Gulnora",
        last_name="Kalandarova",
        roles={Role.TEACHER},
        status=UserStatus.DEACTIVATED,
        login="kalandarova.gulnora",
    )

    ref = await ensure(auth_world, emis_id=None)

    assert ref.id != gone.id
