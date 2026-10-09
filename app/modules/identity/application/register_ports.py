"""Ports of the EMIS use cases: EMIS client, Vault, accounts, Redis and B1 services."""

import datetime as dt
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, Protocol, Self, TypeVar
from uuid import UUID

from app.modules.identity.application.register_models import (
    AccountSnapshot,
    EmisSecret,
    NewStudentAccount,
)
from app.shared.contracts.emis import (
    EmisClass,
    EmisClassHour,
    EmisProfile,
    EmisSubject,
    EmisSubjectRatings,
)
from app.shared.db.uow import AfterCommit
from app.shared.notifications import AuditDraft, NotificationDraft

from pydantic import BaseModel

# - - - EMIS and Vault - - -


class EmisTimetableSource(Protocol):
    """Where the dated classes of a student come from (ACA-1)."""

    async def timetable(
        self, token: str, begin: dt.date, end: dt.date
    ) -> list[EmisClass]:
        """Return the token's classes on the dates begin..end (inclusive)."""
        ...


class EmisApi(EmisTimetableSource, Protocol):
    """The EMIS HTTP API, returning normalized data (client or fake)."""

    async def login(self, login: str, password: str) -> str:
        """Return an access token; raise EmisAuthError on HTTP 401."""
        ...

    async def profile(self, token: str) -> EmisProfile:
        """Return the student's profile."""
        ...

    async def curriculum(self, token: str) -> list[EmisSubject]:
        """Return the subjects of the student's curriculum."""
        ...

    async def ratings(
        self, token: str, subject_id: int, semester: int
    ) -> EmisSubjectRatings:
        """Return marks and the semester rating of one subject."""
        ...

    async def class_hours(self, token: str) -> list[EmisClassHour]:
        """Return the bells (``student-profiles/class-hours/``)."""
        ...


class CredentialStore(Protocol):
    """Vault: Transit encryption and the KV secret of each student."""

    async def encrypt(self, plaintext: str) -> str:
        """Encrypt with the Transit key; return the ciphertext."""
        ...

    async def decrypt(self, ciphertext: str) -> str:
        """Decrypt a Transit ciphertext."""
        ...

    async def write(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        """Write the secret at ``ref`` (a new version if it exists)."""
        ...

    async def replace(
        self, ref: UUID, *, login: str, password_enc: str, access_token: str
    ) -> None:
        """Write the secret and drop all older versions."""
        ...

    async def read(self, ref: UUID) -> EmisSecret:
        """Read the secret; raise CredentialNotFoundError if it is missing."""
        ...

    async def update_token(self, ref: UUID, token: str) -> None:
        """Store a fresh EMIS access token."""
        ...

    async def destroy(self, ref: UUID) -> None:
        """Delete the secret and all its versions (idempotent)."""
        ...


# - - - Accounts - - -


class AccountRepository(Protocol):
    """The id.users queries and writes of the EMIS use cases."""

    async def get(self, user_id: UUID) -> AccountSnapshot | None:
        """Load one account."""
        ...

    async def get_by_emis_student_id(
        self, emis_student_id: int
    ) -> AccountSnapshot | None:
        """Load the account linked to an EMIS profile, if any."""
        ...

    async def lock_logins(self) -> None:
        """Serialize concurrent registrations until the transaction ends."""
        ...

    async def taken_logins(self, prefix: str) -> set[str]:
        """Return the lowercase logins that start with ``prefix``."""
        ...

    async def email_in_use(self, email: str, *, except_user_id: UUID | None) -> bool:
        """Return True if the email (case-insensitive) belongs to another user."""
        ...

    async def release_deleted_emis_link(self, emis_student_id: int) -> None:
        """Detach the EMIS profile from a deleted account so it can register again."""
        ...

    async def save_student(self, account: NewStudentAccount) -> None:
        """Insert a new student, or activate the imported one."""
        ...

    async def set_credentials(
        self,
        user_id: UUID,
        *,
        password_hash: str,
        recovery_email: str,
        now: datetime,
    ) -> None:
        """Replace the password and the verified recovery email (reclaim)."""
        ...

    async def set_emis_status(
        self, user_id: UUID, status: Literal["active", "needs_reauth"]
    ) -> None:
        """Set ``emis_status`` (``active`` or ``needs_reauth``)."""
        ...

    async def mark_deleted(self, user_id: UUID, now: datetime) -> None:
        """Set status ``deleted`` and ``deleted_at``."""
        ...

    async def clear_emis_secret(self, user_id: UUID) -> None:
        """Forget the Vault reference after the secret was destroyed."""
        ...


class EmisUnitOfWork(Protocol):
    """A transaction over the identity tables (implemented by SqlUnitOfWork)."""

    @property
    def accounts(self) -> AccountRepository:
        """The account repository bound to this transaction."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    def notify(self, *drafts: NotificationDraft) -> None:
        """Queue notifications for the commit."""
        ...

    def audit(self, *drafts: AuditDraft) -> None:
        """Queue audit events for the commit."""
        ...

    def after_commit(self, hook: AfterCommit) -> None:
        """Run a coroutine after a successful commit."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


UnitOfWorkFactory = Callable[[], EmisUnitOfWork]


# - - - Redis flows and passwords - - -


T = TypeVar("T", bound=BaseModel)


class PendingStore(Protocol[T]):
    """Short-lived flow state keyed by a random bearer token."""

    async def create(self, value: T) -> str:
        """Store the value and return the new token."""
        ...

    async def get(self, token: str) -> T | None:
        """Load the value; None if it expired or never existed."""
        ...

    async def save(self, token: str, value: T) -> None:
        """Overwrite the value, keeping the remaining lifetime."""
        ...

    async def delete(self, token: str) -> None:
        """Forget the value."""
        ...


class PasswordHasher(Protocol):
    """Argon2id hashing."""

    async def hash(self, password: str) -> str:
        """Return the Argon2id hash."""
        ...

    async def verify(self, password_hash: str, password: str) -> bool:
        """Return True if the password matches."""
        ...


# - - - Services of the login app (task B1), by protocol - - -


class LoginAcceptorPort(Protocol):
    """Accepts a Hydra login challenge for a user (B1 ``LoginAcceptor``)."""

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
        """Return the redirect URL."""
        ...


class AccountRevokerPort(Protocol):
    """Revokes every session, token and connector of a user (B1 ``AccountRevoker``)."""

    async def revoke_everything(
        self, user_id: UUID, *, keep_telegram: bool = False
    ) -> None:
        """Bump the auth epoch and revoke everything."""
        ...


class EmailSenderPort(Protocol):
    """Sends a templated email (B1 ``EmailSender``)."""

    async def send(
        self, to: str, template: str, params: dict[str, Any], locale: str
    ) -> None:
        """Render the template and send."""
        ...


class OtpPort(Protocol):
    """One-time codes in Redis (B1 ``OtpStore``)."""

    async def issue(self, purpose: str, subject_key: str) -> str:
        """Create a 6-digit code and return it."""
        ...

    async def verify(self, purpose: str, subject_key: str, code: str) -> bool:
        """Check the code; consume it on success."""
        ...
