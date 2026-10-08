"""ID-28, UF-ID-15: reclaiming an account with EMIS credentials."""

from uuid import UUID

from app.modules.identity.application.register_errors import (
    EmailInUseError,
    EmailNotSetError,
    OtpCodeInvalidError,
    ReclaimForbiddenError,
    RegistrationExpiredError,
    UserNotFoundError,
    WeakPasswordError,
)
from app.shared.actor import Role
from app.shared.contracts.emis import EmisAuthFailed
from app.shared.contracts.identity import UserStatus
from app.shared.ids import hash_token
from tests.identity.emis.fakes import make_account
from tests.identity.emis.world import World

import pytest

NEW_PASSWORD = "NewPass456"


async def registered_student(world: World) -> UUID:
    _, registered = await world.register()
    world.emails.sent.clear()
    return registered.user_id


async def begin(world: World, *, emis_password: str = "password") -> str:
    started = await world.reclaim_start.execute(
        emis_login="student01", emis_password=emis_password, ip="10.0.0.9"
    )
    return started.reclaim_token


async def mail_code(world: World, token: str, email: str = "new@example.com") -> str:
    await world.reclaim_email_code.execute(reclaim_token=token, email=email)
    return world.emails.last_code()


async def finish(
    world: World, token: str, code: str, password: str = NEW_PASSWORD
) -> None:
    await world.reclaim_complete.execute(
        reclaim_token=token,
        new_password=password,
        email_code=code,
        ip="10.0.0.9",
        user_agent="pytest",
    )


async def test_start_finds_the_account_linked_to_the_emis_profile(
    world: World,
) -> None:
    """ID-28: EMIS credentials identify the account."""
    user_id = await registered_student(world)

    started = await world.reclaim_start.execute(
        emis_login="student01", emis_password="password", ip="10.0.0.9"
    )

    assert started.login == "abdullayev.alisher"
    pending = await world.pending_reclaims.get(started.reclaim_token)
    assert pending is not None
    assert pending.user_id == user_id
    assert pending.locale == "en"


async def test_an_emis_profile_without_an_account_is_not_found(world: World) -> None:
    """UF-ID-15: nothing to reclaim."""
    with pytest.raises(UserNotFoundError):
        await begin(world)


async def test_wrong_emis_credentials_count_toward_the_registration_limits(
    world: World,
) -> None:
    """UF-ID-15 2a: reclaim is throttled like registration."""
    await registered_student(world)

    with pytest.raises(EmisAuthFailed):
        await begin(world, emis_password="nope")

    assert await world.redis.get("rl:reg-ip:10.0.0.9") == "1"


async def test_an_administration_account_cannot_be_reclaimed(world: World) -> None:
    """UF-ID-15 2b: "Contact Administration"."""
    user_id = await registered_student(world)
    world.repo.accounts[user_id].roles = frozenset({Role.STUDENT, Role.ADMIN})

    with pytest.raises(ReclaimForbiddenError):
        await begin(world)


async def test_a_blocked_account_cannot_be_reclaimed(world: World) -> None:
    """ID-28: blocking is Administration's decision, EMIS credentials do not undo it."""
    user_id = await registered_student(world)
    world.repo.accounts[user_id].status = UserStatus.BLOCKED

    with pytest.raises(ReclaimForbiddenError):
        await begin(world)


async def test_complete_replaces_password_email_and_secret_and_revokes_everything(
    world: World,
) -> None:
    """ID-28: new password, new verified email, new EMIS secret, all sessions gone."""
    user_id = await registered_student(world)
    ref = world.secret_ref_of(user_id)
    world.emis.passwords["student01"] = "changed-in-emis"
    world.repo.accounts[user_id].emis_status = "needs_reauth"
    token = await begin(world, emis_password="changed-in-emis")
    code = await mail_code(world, token)

    await finish(world, token, code)

    account = world.repo.accounts[user_id]
    assert account.password_hash == f"hash:{NEW_PASSWORD}"
    assert account.recovery_email == "new@example.com"
    assert account.emis_status == "active"
    secret = world.store.secrets[ref]
    assert await world.store.decrypt(secret.password_enc) == "changed-in-emis"
    assert world.store.replaced == [ref]
    assert world.revoker.revoked == [user_id]
    assert [a.type for a in world.ledger.audits][-1] == "account.reclaimed"
    assert await world.redis.keys("reclaim:*") == []


async def test_the_old_email_gets_a_notice(world: World) -> None:
    """ID-28: the previous owner of the address is told."""
    await registered_student(world)
    token = await begin(world)
    code = await mail_code(world, token)

    await finish(world, token, code)

    to, template, params, locale = world.emails.sent[-1]
    assert (to, template, locale) == ("aleksey@example.com", "notice", "en")
    assert params["text_key"] == "id-mail-reclaimed-notice"


async def test_the_accounts_own_email_may_be_kept_without_a_notice(
    world: World,
) -> None:
    """ID-28: reclaiming because of someone else's registration keeps the email."""
    await registered_student(world)
    token = await begin(world)
    code = await mail_code(world, token, email="aleksey@example.com")

    await finish(world, token, code)

    assert [t for _, t, _, _ in world.emails.sent] == ["otp"]


async def test_an_email_of_another_account_is_refused(world: World) -> None:
    """ID-4: the new email must be free."""
    await registered_student(world)
    world.repo.add(make_account(email="taken@example.com", emis_student_id=1))
    token = await begin(world)

    with pytest.raises(EmailInUseError):
        await mail_code(world, token, email="taken@example.com")


async def test_a_weak_password_or_a_wrong_code_changes_nothing(world: World) -> None:
    """ID-4: nothing is revoked until the reclaim really happens."""
    user_id = await registered_student(world)
    token = await begin(world)
    code = await mail_code(world, token)

    with pytest.raises(WeakPasswordError):
        await finish(world, token, code, password="weak")
    with pytest.raises(OtpCodeInvalidError):
        await finish(world, token, "000000")

    assert world.repo.accounts[user_id].password_hash == "hash:Secret123"
    assert world.revoker.revoked == []
    assert world.store.replaced == []
    assert ("verify_email", hash_token(token)) in world.otp.codes


async def test_a_mail_failure_does_not_undo_the_reclaim(world: World) -> None:
    """ID-28: the notice is best effort."""
    user_id = await registered_student(world)
    token = await begin(world)
    code = await mail_code(world, token)
    world.emails.fail = True

    await finish(world, token, code)

    assert world.repo.accounts[user_id].recovery_email == "new@example.com"
    assert world.revoker.revoked == [user_id]


async def test_unknown_reclaim_tokens_are_gone(world: World) -> None:
    """ID-28: the flow lives 30 minutes."""
    with pytest.raises(RegistrationExpiredError):
        await world.reclaim_email_code.execute(
            reclaim_token="x" * 43, email="a@example.com"
        )
    with pytest.raises(RegistrationExpiredError):
        await finish(world, "x" * 43, "123456")


async def test_the_email_step_cannot_be_skipped(world: World) -> None:
    """ID-28: a new verified email is part of the reclaim."""
    await registered_student(world)
    token = await begin(world)

    with pytest.raises(EmailNotSetError):
        await finish(world, token, "123456")


async def test_an_email_taken_in_the_meantime_changes_nothing(world: World) -> None:
    """ID-4: checked before the Vault secret is replaced."""
    user_id = await registered_student(world)
    token = await begin(world)
    code = await mail_code(world, token)
    world.repo.add(make_account(email="new@example.com", emis_student_id=1))

    with pytest.raises(EmailInUseError):
        await finish(world, token, code)

    assert world.store.replaced == []
    assert world.revoker.revoked == []
    assert world.repo.accounts[user_id].recovery_email == "aleksey@example.com"
