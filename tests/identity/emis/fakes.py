"""Fakes for the ports of the EMIS use cases (B2); the real ones are in B1 and B3."""

import datetime as dt
from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, Self
from uuid import UUID

from app.modules.identity.application.register_models import (
    AccountSnapshot,
    EmisAuthError,
    EmisRequestError,
    NewStudentAccount,
)
from app.modules.identity.infrastructure.emis.fake import FAKE_PASSWORD, FakeEmisClient
from app.shared.actor import Role
from app.shared.base_error import ConflictError
from app.shared.clock import Clock
from app.shared.contracts.academic import StudentRef
from app.shared.contracts.emis import (
    EmisClass,
    EmisClassHour,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)
from app.shared.contracts.identity import UserStatus
from app.shared.db.uow import AfterCommit
from app.shared.ids import new_id
from app.shared.notifications import AuditDraft, NotificationDraft

# - - - EMIS - - -


class ControlledEmis:
    """The fake EMIS plus switches: outage, revoked tokens, changed passwords."""

    def __init__(self, clock: Clock) -> None:
        """Wrap a FakeEmisClient."""
        self._inner = FakeEmisClient(clock)
        self.calls: list[str] = []
        self.revoked: set[str] = set()
        self.passwords: dict[str, str] = {}
        self.profiles: dict[str, EmisProfile] = {}
        self.down = False
        self.timetable_error: Exception | None = None

    def revoke(self, token: str) -> None:
        """Make EMIS answer 401 for this token."""
        self.revoked.add(token)

    def _check(self, token: str) -> None:
        if self.down:
            raise EmisRequestError("EMIS is down")
        if token in self.revoked:
            raise EmisAuthError()

    async def login(self, login: str, password: str) -> str:
        """Log in; honours ``down`` and ``passwords``."""
        self.calls.append("login")
        if self.down:
            raise EmisRequestError("EMIS is down")
        if password != self.passwords.get(login.lower(), FAKE_PASSWORD):
            raise EmisAuthError()
        token = await self._inner.login(login, FAKE_PASSWORD)
        self.revoked.discard(token)
        return token

    async def profile(self, token: str) -> EmisProfile:
        """Return the profile (``profiles[login]`` overrides the fake one)."""
        self.calls.append("profile")
        self._check(token)
        profile = await self._inner.profile(token)
        login = token.removeprefix("fake-token:")
        return self.profiles.get(login, profile)

    async def curriculum(self, token: str) -> list[EmisSubject]:
        """Return the subjects."""
        self.calls.append("curriculum")
        self._check(token)
        return await self._inner.curriculum(token)

    async def ratings(
        self, token: str, subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return the ratings."""
        self.calls.append("ratings")
        self._check(token)
        return await self._inner.ratings(token, subject_id, semester)

    async def class_hours(self, token: str) -> list[EmisClassHour]:
        """Return the bells."""
        self.calls.append("class_hours")
        self._check(token)
        return await self._inner.class_hours(token)

    async def timetable(
        self, token: str, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the student's classes on begin..end."""
        self.calls.append("timetable")
        self._check(token)
        if self.timetable_error is not None:
            raise self.timetable_error
        return await self._inner.timetable(token, begin, end)


# - - - Services of B1 and B3 - - -


class FakeLoginAcceptor:
    """Accepts a challenge by returning a URL; can be told to fail."""

    def __init__(self) -> None:
        """Start empty."""
        self.accepted: list[tuple[str, UUID, list[str]]] = []
        self.fail = False

    async def accept(
        self,
        challenge: str,
        user_id: UUID,
        *,
        amr: list[str],
        ip: str | None,
        user_agent: str | None,
        remember: bool,
    ) -> str:
        """Record the call."""
        if self.fail:
            raise RuntimeError("hydra is down")
        self.accepted.append((challenge, user_id, amr))
        return f"https://hydra.test/continue?c={challenge}"


class FakeAccountRevoker:
    """Records who was logged out everywhere."""

    def __init__(self) -> None:
        """Start empty."""
        self.revoked: list[UUID] = []

    async def revoke_everything(
        self, user_id: UUID, *, keep_telegram: bool = False
    ) -> None:
        """Record the call."""
        self.revoked.append(user_id)


class FakeEmailSender:
    """Records sent emails."""

    def __init__(self) -> None:
        """Start empty."""
        self.sent: list[tuple[str, str, dict[str, Any], str]] = []
        self.fail = False

    async def send(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> None:
        """Record the email."""
        if self.fail:
            raise RuntimeError("smtp is down")
        self.sent.append((to, template, params, locale))

    def last_code(self) -> str:
        """Return the code of the last ``otp`` email."""
        codes = [p["code"] for _, t, p, _ in self.sent if t == "otp"]
        return str(codes[-1])


class FakeOtpStore:
    """Codes with 3 attempts, like B1's OtpStore (no cooldown here)."""

    def __init__(self) -> None:
        """Start empty."""
        self.codes: dict[tuple[str, str], tuple[str, int]] = {}
        self._counter = 100000

    async def issue(self, purpose: str, subject_key: str) -> str:
        """Create a new code, replacing the old one."""
        self._counter += 1
        code = str(self._counter)
        self.codes[(purpose, subject_key)] = (code, 3)
        return code

    async def verify(self, purpose: str, subject_key: str, code: str) -> bool:
        """Check the code; three misses invalidate it."""
        key = (purpose, subject_key)
        stored = self.codes.get(key)
        if stored is None:
            return False
        real, attempts = stored
        if code == real:
            del self.codes[key]
            return True
        if attempts <= 1:
            del self.codes[key]
        else:
            self.codes[key] = (real, attempts - 1)
        return False


class PlainHasher:
    """A fast stand-in for Argon2 in unit tests."""

    async def hash(self, password: str) -> str:
        """Return a reversible fake hash."""
        return f"hash:{password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        """Compare with the fake hash."""
        return password_hash == f"hash:{password}"


class FakeEnrollment:
    """AcademicEnrollment of B3: records calls; ``imports`` drives name matching."""

    def __init__(self) -> None:
        """Start empty."""
        self.ensured: list[dict[str, Any]] = []
        self.subjects_synced: list[tuple[UUID, int]] = []
        self.left: list[tuple[UUID, str]] = []
        self.imported: UUID | None = None
        self.fail_ensure = False
        self.needs_timetable = False
        self.group_id = new_id()

    async def ensure_student(
        self,
        *,
        user_id: UUID,
        group_emis_id: int,
        group_name: str,
        current_semester: int | None,
        curriculum_id: int | None,
    ) -> StudentRef:
        """Record the call; optionally fail."""
        if self.fail_ensure:
            raise RuntimeError("academic is down")
        self.ensured.append(
            {
                "user_id": user_id,
                "group_emis_id": group_emis_id,
                "group_name": group_name,
                "current_semester": current_semester,
                "curriculum_id": curriculum_id,
            }
        )
        return StudentRef(
            user_id=user_id,
            group_id=self.group_id,
            group_name=group_name,
            subgroup=None,
            status="active",
            synced_at=None,
            needs_timetable=self.needs_timetable,
        )

    async def find_imported_student(
        self,
        *,
        emis_student_id: int | None,
        first_name: str,
        last_name: str,
        group_name: str,
    ) -> UUID | None:
        """Return the configured import match."""
        return self.imported

    async def sync_subjects(
        self, *, group_id: UUID, subjects: Sequence[EmisSubject]
    ) -> None:
        """Record the call."""
        self.subjects_synced.append((group_id, len(subjects)))

    async def mark_left(self, user_id: UUID, *, reason: str) -> None:
        """Record the call."""
        self.left.append((user_id, reason))


# - - - Accounts and the unit of work - - -


def make_account(
    *,
    user_id: UUID | None = None,
    login: str | None = "brastilov.aleksey",
    status: UserStatus = UserStatus.ACTIVE,
    roles: frozenset[Role] = frozenset({Role.STUDENT}),
    first_name: str = "Aleksey",
    last_name: str = "Brastilov",
    email: str | None = "old@example.com",
    password: str | None = "Secret123",
    otp_enabled: bool = False,
    emis_student_id: int | None = 78201,
    vault_ref: UUID | None = None,
    emis_status: Literal["active", "needs_reauth"] | None = "active",
    locale: str = "en",
) -> AccountSnapshot:
    """Build an account snapshot with sensible defaults."""
    return AccountSnapshot(
        id=user_id or new_id(),
        login=login,
        status=status,
        roles=roles,
        first_name=first_name,
        last_name=last_name,
        middle_name=None,
        recovery_email=email,
        password_hash=None if password is None else f"hash:{password}",
        otp_enabled=otp_enabled,
        locale=locale,
        emis_student_id=emis_student_id,
        emis_vault_ref=vault_ref,
        emis_status=emis_status,
    )


@dataclass(slots=True)
class Ledger:
    """What committed transactions queued."""

    audits: list[AuditDraft] = field(default_factory=list)
    notifications: list[NotificationDraft] = field(default_factory=list)
    commits: int = 0


class InMemoryAccountRepository:
    """id.users in a dict; the unit of work restores it on rollback."""

    def __init__(self) -> None:
        """Start empty."""
        self.accounts: dict[UUID, AccountSnapshot] = {}

    def add(self, account: AccountSnapshot) -> AccountSnapshot:
        """Insert a prepared account."""
        self.accounts[account.id] = account
        return account

    async def get(self, user_id: UUID) -> AccountSnapshot | None:
        """Load one account."""
        account = self.accounts.get(user_id)
        return None if account is None else copy(account)

    async def get_by_emis_student_id(
        self, emis_student_id: int
    ) -> AccountSnapshot | None:
        """Load by EMIS profile id."""
        for account in self.accounts.values():
            if account.emis_student_id == emis_student_id:
                return copy(account)
        return None

    async def lock_logins(self) -> None:
        """Nothing to lock in memory."""

    async def taken_logins(self, prefix: str) -> set[str]:
        """Logins starting with the prefix."""
        return {
            a.login.lower()
            for a in self.accounts.values()
            if a.login and a.login.lower().startswith(prefix.lower())
        }

    async def email_in_use(self, email: str, *, except_user_id: UUID | None) -> bool:
        """Case-insensitive email check."""
        return any(
            a.recovery_email
            and a.recovery_email.lower() == email.lower()
            and a.id != except_user_id
            for a in self.accounts.values()
        )

    async def release_deleted_emis_link(self, emis_student_id: int) -> None:
        """Detach the EMIS id from deleted accounts."""
        for account in self.accounts.values():
            if (
                account.emis_student_id == emis_student_id
                and account.status is UserStatus.DELETED
            ):
                account.emis_student_id = None

    async def save_student(self, account: NewStudentAccount) -> None:
        """Insert a student or activate the import."""
        existing = self.accounts.get(account.user_id)
        if account.activates_import:
            if existing is None or existing.status is not UserStatus.UNREGISTERED:
                raise ConflictError(support_details="imported account is not free")
            existing.status = UserStatus.ACTIVE
        else:
            existing = AccountSnapshot(
                id=account.user_id,
                login=None,
                status=UserStatus.ACTIVE,
                roles=frozenset({Role.STUDENT}),
                first_name="",
                last_name="",
                middle_name=None,
                recovery_email=None,
                password_hash=None,
                otp_enabled=False,
                locale=account.locale,
                emis_student_id=None,
                emis_vault_ref=None,
                emis_status=None,
            )
            self.accounts[account.user_id] = existing
        existing.login = account.login
        existing.password_hash = account.password_hash
        existing.first_name = account.first_name
        existing.last_name = account.last_name
        existing.middle_name = account.middle_name
        existing.recovery_email = account.recovery_email
        existing.emis_student_id = account.emis_student_id
        existing.emis_vault_ref = account.emis_vault_ref
        existing.emis_status = "active"
        existing.locale = account.locale

    async def set_credentials(
        self,
        user_id: UUID,
        *,
        password_hash: str,
        recovery_email: str,
        now: datetime,
    ) -> None:
        """Replace password and email."""
        account = self.accounts[user_id]
        account.password_hash = password_hash
        account.recovery_email = recovery_email

    async def set_emis_status(
        self, user_id: UUID, status: Literal["active", "needs_reauth"]
    ) -> None:
        """Set emis_status."""
        self.accounts[user_id].emis_status = status

    async def mark_deleted(self, user_id: UUID, now: datetime) -> None:
        """Mark the account deleted."""
        self.accounts[user_id].status = UserStatus.DELETED

    async def clear_emis_secret(self, user_id: UUID) -> None:
        """Forget the Vault reference."""
        account = self.accounts[user_id]
        account.emis_vault_ref = None
        account.emis_status = None


class FakeEmisUnitOfWork:
    """Transaction semantics over the in-memory repository."""

    def __init__(self, repository: InMemoryAccountRepository, ledger: Ledger) -> None:
        """Bind to the shared repository and ledger."""
        self._repository = repository
        self._ledger = ledger
        self._backup: dict[UUID, AccountSnapshot] = {}
        self._hooks: list[AfterCommit] = []
        self._audits: list[AuditDraft] = []
        self._notifications: list[NotificationDraft] = []
        self.committed = False

    @property
    def accounts(self) -> InMemoryAccountRepository:
        """The repository of this transaction."""
        return self._repository

    async def __aenter__(self) -> Self:
        """Remember the state for a rollback."""
        self._backup = {k: copy(v) for k, v in self._repository.accounts.items()}
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        if not self.committed:
            self._repository.accounts = self._backup

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications."""
        self._notifications.extend(drafts)

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events."""
        self._audits.extend(drafts)

    def after_commit(self, hook: AfterCommit) -> None:
        """Queue a hook."""
        self._hooks.append(hook)

    async def commit(self) -> None:
        """Keep the changes, publish audits, run hooks."""
        self.committed = True
        self._ledger.commits += 1
        self._ledger.audits.extend(self._audits)
        self._ledger.notifications.extend(self._notifications)
        for hook in self._hooks:
            await hook()


def describe(account: AccountSnapshot) -> AccountSnapshot:
    """Return a copy (tests compare after further changes)."""
    return replace(account)
