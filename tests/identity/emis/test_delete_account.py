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


async def test_deletion_closes_the_account_and_destroys_the_secret(
    world: World,
) -> None:
    """ID-9, ID-29: deleted, logged out everywhere, secret gone, 30 days to go."""
    user_id = await registered(world)
    ref = world.secret_ref_of(user_id)

    closes_on = await delete(world, user_id)

    assert closes_on == date(2026, 11, 5)
    account = world.repo.accounts[user_id]
    assert account.status is UserStatus.DELETED
    assert world.revoker.revoked == [user_id]
    assert world.enrollment.left == [(user_id, "deleted")]
    assert ref in world.store.destroyed
    assert world.store.secrets == {}
    assert account.emis_vault_ref is None
    assert world.ledger.audits[-1].type == "account.deleted"


async def test_files_and_links_of_the_student_are_scheduled_for_removal(
    world: World,
) -> None:
    """UF-ID-16 step 3: files are deleted, links return 410."""
    user_id = await registered(world)

    await delete(world, user_id)

    assert world.kicker.calls == [
        ("files.delete_owner", {"user_id": str(user_id)}),
        ("links.revoke_owner", {"user_id": str(user_id)}),
        ("notebooks.delete_owner", {"user_id": str(user_id)}),
    ]


async def test_the_recovery_email_gets_a_notice_with_the_date(world: World) -> None:
    """ID-29: the student is told when the data goes."""
    user_id = await registered(world)

    await delete(world, user_id)

    to, template, params, _ = world.emails.sent[-1]
    assert (to, template) == ("aleksey@example.com", "notice")
    assert params["text_key"] == "id-mail-deleted-notice"
    assert params["text_params"] == {"closes_on": "2026-11-05"}


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

    assert world.repo.accounts[user_id].status is UserStatus.DELETED


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


async def test_a_vault_outage_is_retried_by_a_task(world: World) -> None:
    """ID-9: the deletion succeeds; destroying the secret is retried later."""
    user_id = await registered(world)
    world.store.down = True

    await delete(world, user_id)

    assert world.repo.accounts[user_id].status is UserStatus.DELETED
    assert ("identity.destroy_emis_secret", {"user_id": str(user_id)}) in (
        world.kicker.calls
    )
    assert len(world.store.secrets) == 1


async def test_a_mail_failure_does_not_undo_the_deletion(world: World) -> None:
    """ID-29: the notice is best effort."""
    user_id = await registered(world)
    world.emails.fail = True

    await delete(world, user_id)

    assert world.repo.accounts[user_id].status is UserStatus.DELETED
