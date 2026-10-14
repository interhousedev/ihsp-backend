"""ID-1, ID-4, ID-5, ID-6, ACA-18, SYNC-4: finishing a registration."""

from app.modules.identity.application.register_errors import (
    EmailInUseError,
    EmailNotSetError,
    EmisAlreadyLinkedError,
    ImportMatchUnconfirmedError,
    OtpCodeInvalidError,
    RegistrationExpiredError,
    WeakPasswordError,
)
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import hash_token
from tests.identity.emis.fakes import make_account
from tests.identity.emis.world import NEW_PASSWORD, World

import pytest


async def prepared(world: World, login: str = "student01") -> str:
    """Start a registration and mail the code; return the token."""
    started = await world.register_start.execute(
        emis_login=login, emis_password="password", ip="10.0.0.1", locale="en"
    )
    await world.register_email_code.execute(
        registration_token=started.registration_token, email="aleksey@example.com"
    )
    return started.registration_token


def code_for(world: World, token: str) -> str:
    """The code mailed for this registration (several can be pending)."""
    return world.otp.codes[("verify_email", hash_token(token))][0]


async def complete(
    world: World,
    token: str,
    *,
    password: str = NEW_PASSWORD,
    code: str | None = None,
    confirm: bool = True,
    challenge: str | None = None,
) -> str:
    registered = await world.register_complete.execute(
        registration_token=token,
        password=password,
        email_code=code or code_for(world, token),
        confirm_import_match=confirm,
        login_challenge=challenge,
        ip="10.0.0.1",
        user_agent="pytest",
    )
    return registered.login


async def test_registration_creates_the_account_secret_and_student(
    world: World,
) -> None:
    """ID-1, ID-4, ID-5, ID-6: account, Vault secret, student record, backfill."""
    started, registered = await world.register()

    account = world.repo.accounts[registered.user_id]
    assert account.status is UserStatus.ACTIVE
    assert account.roles == frozenset({Role.STUDENT})
    assert (account.login, registered.login) == ("abdullayev.alisher",) * 2
    assert account.recovery_email == "aleksey@example.com"
    assert account.password_hash == f"hash:{NEW_PASSWORD}"
    assert (account.first_name, account.last_name) == ("Alisher", "Abdullayev")
    assert (account.emis_student_id, account.emis_status) == (78201, "active")
    secret = world.store.secrets[world.secret_ref_of(registered.user_id)]
    assert secret.login == "student01"
    assert await world.store.decrypt(secret.password_enc) == "password"
    assert secret.access_token == "fake-token:student01"
    assert world.enrollment.ensured == [
        {
            "user_id": registered.user_id,
            "group_emis_id": 3292,
            "group_name": "2TN2",
            "current_semester": 3,
            "curriculum_id": 2124,
        }
    ]
    assert world.enrollment.subjects_synced == [(world.enrollment.group_id, 8)]
    assert world.kicker.calls == [
        ("academic.backfill_student", {"user_id": str(registered.user_id)}),
        (
            "academic.sync_student_all",
            {"user_id": str(registered.user_id), "with_marks": False},
        ),
    ]
    assert [a.type for a in world.ledger.audits] == ["user.registered"]
    assert await world.redis.keys("reg:*") == []
    assert registered.redirect_to is None
    assert started.registration_token not in str(world.ledger.audits)


async def test_the_login_challenge_is_accepted_and_its_redirect_returned(
    world: World,
) -> None:
    """UF-ID-01 step 9: the student is logged in and sent back."""
    _, registered = await world.register(challenge="abc")

    assert registered.redirect_to == "https://hydra.test/continue?c=abc"
    assert world.acceptor.accepted == [("abc", registered.user_id, ["pwd"])]


async def test_a_failed_login_accept_does_not_undo_the_registration(
    world: World,
) -> None:
    """UF-ID-01: the account exists; the page falls back to the login form."""
    world.acceptor.fail = True

    _, registered = await world.register(challenge="abc")

    assert registered.redirect_to is None
    assert registered.user_id in world.repo.accounts


async def test_a_weak_password_lists_the_broken_rules_and_keeps_the_code(
    world: World,
) -> None:
    """ID-4: the policy is checked before the code is used up."""
    token = await prepared(world)

    with pytest.raises(WeakPasswordError) as caught:
        await complete(world, token, password="short")

    assert caught.value.params["errors"] == [
        "id-password-too-short",
        "id-password-no-digit",
        "id-password-no-upper",
    ]
    assert world.store.secrets == {}
    assert ("verify_email", hash_token(token)) in world.otp.codes


async def test_a_wrong_code_is_refused_and_three_misses_kill_it(world: World) -> None:
    """ID-14: 3 attempts, then the code is invalidated."""
    token = await prepared(world)
    good = code_for(world, token)

    for _ in range(3):
        with pytest.raises(OtpCodeInvalidError):
            await complete(world, token, code="000000")
    with pytest.raises(OtpCodeInvalidError):
        await complete(world, token, code=good)

    assert world.repo.accounts == {}


async def test_the_email_step_cannot_be_skipped(world: World) -> None:
    """ID-4: no email, no account."""
    started = await world.register_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.1", locale="en"
    )

    with pytest.raises(EmailNotSetError):
        await complete(world, started.registration_token, code="123456")


async def test_an_unknown_token_is_gone(world: World) -> None:
    """ID-1: the flow lives 30 minutes."""
    with pytest.raises(RegistrationExpiredError):
        await complete(world, "x" * 43, code="123456")


async def test_an_import_found_by_name_must_be_confirmed(world: World) -> None:
    """ACA-18: "Is this you?" has to be answered yes."""
    imported = world.repo.add(
        make_account(
            login=None,
            status=UserStatus.UNREGISTERED,
            email=None,
            password=None,
            emis_student_id=None,
        )
    )
    world.enrollment.imported = imported.id
    token = await prepared(world)

    with pytest.raises(ImportMatchUnconfirmedError):
        await complete(world, token, confirm=False)
    login = await complete(world, token, confirm=True)

    assert world.repo.accounts[imported.id].status is UserStatus.ACTIVE
    assert login == "abdullayev.alisher"


async def test_the_imported_account_is_activated_not_duplicated(
    world: World,
) -> None:
    """ACA-18: registration claims the account the import created."""
    imported = world.repo.add(
        make_account(
            login=None,
            status=UserStatus.UNREGISTERED,
            email=None,
            password=None,
            emis_student_id=78201,
            first_name="ПЕТР",
            last_name="ПЕТРОВ",
        )
    )

    _, registered = await world.register()

    assert registered.user_id == imported.id
    assert list(world.repo.accounts) == [imported.id]
    account = world.repo.accounts[imported.id]
    assert account.status is UserStatus.ACTIVE
    assert (account.first_name, account.last_name) == ("Alisher", "Abdullayev")


async def test_the_secret_is_destroyed_and_nothing_saved_when_enrollment_fails(
    world: World,
) -> None:
    """ID-6: no orphan Vault secret, no half-created account; the flow can retry."""
    world.enrollment.fail_ensure = True
    token = await prepared(world)

    with pytest.raises(RuntimeError):
        await complete(world, token)

    assert world.store.secrets == {}
    assert len(world.store.destroyed) == 1
    assert world.repo.accounts == {}
    assert world.kicker.calls == []
    assert await world.pending_registrations.get(token) is not None


async def test_the_second_of_two_parallel_registrations_is_refused(
    world: World,
) -> None:
    """ID-3: two tokens for one EMIS profile cannot both finish."""
    first = await prepared(world)
    second = await prepared(world)
    await complete(world, first)

    with pytest.raises(EmisAlreadyLinkedError):
        await complete(world, second)

    assert len(world.store.secrets) == 1
    assert len(world.repo.accounts) == 1


async def test_an_email_taken_in_the_meantime_is_refused(world: World) -> None:
    """ID-4: the email is checked again inside the transaction."""
    token = await prepared(world)
    world.repo.add(make_account(email="aleksey@example.com", emis_student_id=1))

    with pytest.raises(EmailInUseError):
        await complete(world, token)

    assert world.store.secrets == {}


async def test_a_login_taken_in_the_meantime_gets_a_number(world: World) -> None:
    """ID-5: the login shown at the start is a preview; it is chosen again."""
    token = await prepared(world)
    world.repo.add(make_account(login="abdullayev.alisher", emis_student_id=1))

    login = await complete(world, token)

    assert login == "abdullayev.alisher2"


async def test_a_deleted_account_gives_its_emis_profile_back(world: World) -> None:
    """ID-29: the student can register again after deleting an account."""
    old = world.repo.add(
        make_account(
            login="abdullayev.alisher",
            status=UserStatus.DELETED,
            emis_student_id=78201,
            email="old@example.com",
        )
    )

    _, registered = await world.register()

    assert registered.login == "abdullayev.alisher2"
    assert world.repo.accounts[old.id].emis_student_id is None
    assert world.repo.accounts[registered.user_id].emis_student_id == 78201


@pytest.mark.parametrize("needs_timetable", [True, False])
async def test_every_new_student_syncs_the_timetable_of_their_group(
    world: World, needs_timetable: bool
) -> None:
    """ACA-1: an unknown group is filled; a known one gets the student's own half."""
    world.enrollment.needs_timetable = needs_timetable

    _, registered = await world.register()

    assert world.kicker.names() == [
        "academic.backfill_student",
        "academic.sync_student_all",
    ]
    assert world.kicker.calls[1][1] == {
        "user_id": str(registered.user_id),
        "with_marks": False,
    }


async def test_the_bells_are_left_to_the_timetable_sync(world: World) -> None:
    """ACA-4: the timetable sync refreshes the bells first; no separate task."""
    await world.register()

    assert "academic.sync_class_hours" not in world.kicker.names()


async def test_no_timetable_task_starts_when_the_registration_fails(
    world: World,
) -> None:
    """ACA-1: tasks start after the commit, never for a rolled back account."""
    world.enrollment.needs_timetable = True
    world.enrollment.fail_ensure = True

    with pytest.raises(RuntimeError):
        await world.register()

    assert world.kicker.calls == []
