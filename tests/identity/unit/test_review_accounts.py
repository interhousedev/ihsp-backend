"""The public review accounts: idempotent, can sign in, fit their MCP server."""

from app.bootstrap.seed.review_accounts import (
    LMS,
    REVIEW_ACCOUNTS,
    STUDENT,
    TEACHER,
    ReviewAccount,
    ensure_review_accounts,
)
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.scopes import role_may_use_server
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from tests.identity.support import World

import pytest

CTX = RequestContext(ip="127.0.0.1", user_agent="pytest")
SERVERS = ("student", "teacher", "lms", "admin")


async def _seed(world: World) -> dict[str, object]:
    return dict(
        await ensure_review_accounts(
            world.auth.uow_factory, world.auth.hasher, world.clock
        )
    )


async def test_a_rerun_keeps_the_ids_and_does_not_add_users(auth_world: World) -> None:
    """Running the seed twice leaves one user per account."""
    first = await _seed(auth_world)
    count = len(auth_world.store.users)

    second = await _seed(auth_world)

    assert first == second
    assert len(auth_world.store.users) == count
    assert len(first) == len(REVIEW_ACCOUNTS)


async def test_a_rerun_resets_password_roles_and_status(auth_world: World) -> None:
    """A changed or blocked review account is put back."""
    ids = await _seed(auth_world)
    user = auth_world.user(ids["teacher"])  # type: ignore[arg-type]
    user.roles = {Role.ADMIN}
    user.status = UserStatus.BLOCKED
    user.password_hash = None

    await _seed(auth_world)

    user = auth_world.user(ids["teacher"])  # type: ignore[arg-type]
    assert user.roles == set(TEACHER.roles)
    assert user.status == UserStatus.ACTIVE
    assert await auth_world.auth.hasher.verify(user.password_hash, TEACHER.password)


async def test_accounts_have_no_emis_and_a_suspended_review_mailbox(
    auth_world: World,
) -> None:
    """Nothing links to EMIS, and mail never goes out."""
    ids = await _seed(auth_world)

    for account in REVIEW_ACCOUNTS:
        user = auth_world.user(ids[account.key])  # type: ignore[arg-type]
        assert user.recovery_email == f"{account.login}@review.invalid"
        assert user.recovery_email_verified_at is not None
        assert user.mail_suspended_at is not None
        assert not user.otp_enabled


@pytest.mark.parametrize("account", REVIEW_ACCOUNTS, ids=lambda a: a.key)
async def test_password_login_works(auth_world: World, account: ReviewAccount) -> None:
    """The public password signs the account in."""
    await _seed(auth_world)
    auth_world.hydra.add_login("lc-1")

    result = await auth_world.auth.log_in_with_password.execute(
        "lc-1", account.login, account.password, remember=False, ctx=CTX
    )

    assert result.second_factor is None
    assert result.redirect_to is not None


@pytest.mark.parametrize("account", REVIEW_ACCOUNTS, ids=lambda a: a.key)
def test_each_account_fits_exactly_its_servers(account: ReviewAccount) -> None:
    """The student, teacher and LMS accounts reach their server; admin is no one's."""
    for server in SERVERS:
        allowed = role_may_use_server(account.roles, server)
        if server in account.servers:
            assert allowed, (account.key, server)
    assert not role_may_use_server(account.roles, "admin")


def test_the_three_accounts_cover_the_three_submitted_servers() -> None:
    """Student, teacher and lms are covered; admin is not."""
    covered = {
        server for account in (STUDENT, TEACHER, LMS) for server in account.servers
    }
    assert covered == {"student", "teacher", "lms"}
