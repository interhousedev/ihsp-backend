"""Public review accounts for the ChatGPT app submission (made-up people).

The passwords below are public on purpose: the reviewers of the ChatGPT app need
them (docs/chatgpt-review.md). The accounts hold made-up data only and have no EMIS
link. This file and the docs page are the only places the passwords may appear.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.domain.user import User
from app.modules.identity.ports.password_hasher import PasswordHasher
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Role
from app.shared.clock import Clock
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id

import structlog

log = structlog.get_logger(__name__)

REVIEW_DOMAIN = "review.invalid"


@dataclass(frozen=True, slots=True)
class ReviewAccount:
    """One review account and the MCP servers it covers."""

    key: str
    login: str
    password: str
    first_name: str
    last_name: str
    roles: frozenset[Role]
    servers: tuple[str, ...]

    @property
    def email(self) -> str:
        """The recovery address; the `.invalid` domain never receives mail."""
        return f"{self.login}@{REVIEW_DOMAIN}"


STUDENT = ReviewAccount(
    key="student",
    login="review.student",
    password="IhtReviewStudent-2026",
    first_name="Aziz",
    last_name="Reviewer",
    roles=frozenset({Role.STUDENT}),
    servers=("student",),
)
TEACHER = ReviewAccount(
    key="teacher",
    login="review.teacher",
    password="IhtReviewTeacher-2026",
    first_name="Dilnoza",
    last_name="Reviewer",
    roles=frozenset({Role.TEACHER}),
    servers=("teacher",),
)
LMS = ReviewAccount(
    key="lms",
    login="review.lms",
    password="IhtReviewLms-2026",
    first_name="Timur",
    last_name="Reviewer",
    roles=frozenset({Role.LMS_CREATOR, Role.TEACHER}),
    servers=("lms",),
)
REVIEW_ACCOUNTS: tuple[ReviewAccount, ...] = (STUDENT, TEACHER, LMS)


async def _ensure(
    uow_factory: UowFactory,
    hasher: PasswordHasher,
    clock: Clock,
    account: ReviewAccount,
) -> UUID:
    """Create the account, or put an existing one back to its known state."""
    now = clock.now()
    async with uow_factory() as uow:
        user = await uow.users.get_by_login(account.login)
        created = user is None
        if user is None:
            user = User(
                id=new_id(),
                first_name=account.first_name,
                last_name=account.last_name,
                login=account.login,
            )
        user.first_name = account.first_name
        user.last_name = account.last_name
        if not await hasher.verify(user.password_hash, account.password):
            user.password_hash = await hasher.hash(account.password)
        user.password_change_required = False
        user.roles = set(account.roles)
        user.recovery_email = account.email
        user.recovery_email_verified_at = user.recovery_email_verified_at or now
        user.otp_enabled = False
        user.otp_via_email = False
        user.status = UserStatus.ACTIVE
        user.deleted_at = None
        user.deletion_requested_at = None
        user.mail_suspended_at = user.mail_suspended_at or now
        user.preferences = {**user.preferences, "locale": "en"}
        if created:
            await uow.users.add(user)
        else:
            await uow.users.save(user)
        await uow.commit()
    log.info("seed_review_account", login=account.login, created=created)
    return user.id


async def ensure_review_accounts(
    uow_factory: UowFactory,
    hasher: PasswordHasher,
    clock: Clock,
    accounts: Sequence[ReviewAccount] = REVIEW_ACCOUNTS,
) -> dict[str, UUID]:
    """Create or reset the review accounts; return their user ids by key."""
    return {
        account.key: await _ensure(uow_factory, hasher, clock, account)
        for account in accounts
    }
