"""ID-9, ID-29, UF-ID-16: a student deletes their account."""

from datetime import date
from uuid import UUID

from app.modules.identity.application.register_errors import (
    DeleteForbiddenError,
    OtpCodeInvalidError,
    WrongPasswordError,
)
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from tests.identity.emis.world import NEW_PASSWORD, World

import pytest


def student(user_id: UUID) -> Actor:
    return Actor(user_id=user_id, roles=frozenset({Role.STUDENT}))


async def delete(
    world: World, user_id: UUID, *, password: str = NEW_PASSWORD, otp: str | None = None
) -> date:
    return await world.delete_account.execute(
        student(user_id), password=password, otp_code=otp, ip="10.0.0.1", user_agent="x"
    )


async def registered(world: World) -> UUID:
    _, result = await world.register()
    world.kicker.calls.clear()
    world.emails.sent.clear()
    return result.user_id


async def test_deletion_is_scheduled_and_sessions_are_revoked(world: World) -> None:
    """ID-29: pending for 30 days, logged out everywhere, nothing removed yet."""
    user_id = await registered(world)
    ref = world.secret_ref_of(user_id)

    closes_on = await delete(world, user_id)

    assert closes_on == date(2026, 11, 5)
    account = world.repo.accounts[user_id]
    assert account.status is UserStatus.PENDING_DELETION
    assert world.repo.deletion_requested[user_id] == world.clock.now()
    assert world.revoker.revoked == [user_id]
    assert world.revoker.kept_telegram == [True]
    assert world.enrollment.left == []
    assert world.kicker.calls == []
    assert world.store.destroyed == []
    assert account.emis_vault_ref == ref
    assert world.ledger.audits[-1].type == "account.deletion_requested"


async def test_the_owner_is_told_by_email_and_telegram(world: World) -> None:
    """ID-29: the date and how to restore go to the recovery email and Telegram."""
    user_id = await registered(world)

    await delete(world, user_id)

    to, template, params, _ = world.emails.sent[-1]
    assert (to, template) == ("aleksey@example.com", "notice")
    assert params["text_key"] == "id-mail-deletion-scheduled"
    assert params["text_params"] == {"closes_on": "2026-11-05"}
    assert world.telegram_notices == [(user_id, date(2026, 11, 5))]


async def test_the_purge_waits_for_the_window(world: World) -> None:
    """Nothing is closed before 30 days; then the clean-up tasks start."""
    user_id = await registered(world)
    await delete(world, user_id)
    world.revoker.revoked.clear()
    world.revoker.kept_telegram.clear()

    world.clock.advance(days=29, hours=23)
    assert await world.finalize_account_deletions.execute() == 0
    assert world.repo.accounts[user_id].status is UserStatus.PENDING_DELETION

    world.clock.advance(hours=2)
    assert await world.finalize_account_deletions.execute() == 1

    assert world.repo.accounts[user_id].status is UserStatus.DELETED
    assert world.enrollment.left == [(user_id, "deleted")]
    assert world.revoker.kept_telegram == [False]
    assert [task for task, _ in world.kicker.calls] == [
        "identity.destroy_emis_secret",
        "files.delete_owner",
        "links.revoke_owner",
        "notebooks.delete_owner",
        "library.delete_owner",
    ]
    assert world.ledger.audits[-1].type == "account.deleted"
    assert await world.finalize_account_deletions.execute() == 0


async def test_a_restored_account_is_not_purged(world: World) -> None:
    """A restore at login (status back to active) survives the job."""
    user_id = await registered(world)
    await delete(world, user_id)
    world.repo.accounts[user_id].status = UserStatus.ACTIVE

    world.clock.advance(days=31)

    assert await world.finalize_account_deletions.execute() == 0
    assert world.kicker.calls == []


async def test_a_wrong_password_changes_nothing(world: World) -> None:
    """UF-ID-16 step 2: the password confirms the deletion."""
    user_id = await registered(world)

    with pytest.raises(WrongPasswordError) as caught:
        await delete(world, user_id, password="Wrong123")

    assert caught.value.status == 403  # 401 would log the web client out
    assert world.repo.accounts[user_id].status is UserStatus.ACTIVE
    assert world.revoker.revoked == []
    assert world.store.destroyed == []


async def test_a_student_with_otp_must_send_the_step_up_code(world: World) -> None:
    """UF-ID-16 step 2: password and an OTP when OTP is enabled."""
    user_id = await registered(world)
    world.repo.accounts[user_id].otp_enabled = True

    with pytest.raises(OtpCodeInvalidError):
        await delete(world, user_id)
    with pytest.raises(OtpCodeInvalidError):
        await delete(world, user_id, otp="000000")
    world.otp.codes[("step-up", str(user_id))] = ("654321", 3)
    await delete(world, user_id, otp="654321")

    assert world.repo.accounts[user_id].status is UserStatus.PENDING_DELETION


@pytest.mark.parametrize(
    "roles",
    [
        frozenset({Role.STUDENT, Role.TEACHER}),
        frozenset({Role.TEACHER}),
        frozenset({Role.STUDENT, Role.ADMIN}),
    ],
)
async def test_staff_accounts_cannot_delete_themselves(
    world: World, roles: frozenset[Role]
) -> None:
    """ID-29: only student accounts; staff are closed by Administration."""
    user_id = await registered(world)
    world.repo.accounts[user_id].roles = roles

    with pytest.raises(DeleteForbiddenError):
        await delete(world, user_id)

    assert world.repo.accounts[user_id].status is UserStatus.ACTIVE


async def test_a_blocked_account_cannot_delete_itself(world: World) -> None:
    """ID-11: a block is not escaped by deleting."""
    user_id = await registered(world)
    world.repo.accounts[user_id].status = UserStatus.BLOCKED

    with pytest.raises(DeleteForbiddenError):
        await delete(world, user_id)


async def test_a_mail_failure_does_not_undo_the_deletion(world: World) -> None:
    """ID-29: the notice is best effort."""
    user_id = await registered(world)
    world.emails.fail = True

    await delete(world, user_id)

    assert world.repo.accounts[user_id].status is UserStatus.PENDING_DELETION
