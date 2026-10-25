"""Data and port errors shared by the EMIS use cases."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.shared.actor import Role
from app.shared.contracts.emis import EmisProfile, EmisSubject
from app.shared.contracts.identity import UserStatus

from pydantic import BaseModel

# - - - Errors raised by ports (mapped to BaseError at the use case edge) - - -


class EmisAuthError(Exception):
    """EMIS rejected the credentials or the access token (HTTP 401)."""


class EmisRequestError(Exception):
    """EMIS did not answer, or answered with something unexpected."""


class EmisPausedError(EmisRequestError):
    """EMIS asked us to stop (429 or Retry-After): calls wait ``retry_after``."""

    def __init__(self, retry_after: float) -> None:
        """Store the seconds EMIS asked for."""
        super().__init__("paused")
        self.retry_after = retry_after


class EmisFileRetryError(EmisRequestError):
    """A material download failed upstream (5xx or transport): try it again later."""


class CredentialNotFoundError(Exception):
    """The Vault secret does not exist (never written, or destroyed)."""


class CredentialStoreError(Exception):
    """Vault is unreachable, denied the request or answered unexpectedly."""


# - - - Vault and account data - - -


@dataclass(frozen=True, slots=True)
class EmisSecret:
    """What the ID module keeps in Vault KV for one student."""

    login: str
    password_enc: str
    access_token: str


@dataclass(slots=True)
class AccountSnapshot:
    """The columns of id.users that the EMIS use cases read."""

    id: UUID
    login: str | None
    status: UserStatus
    roles: frozenset[Role]
    first_name: str
    last_name: str
    middle_name: str | None
    recovery_email: str | None
    password_hash: str | None
    otp_enabled: bool
    locale: str
    emis_student_id: int | None
    emis_vault_ref: UUID | None
    emis_status: Literal["active", "needs_reauth"] | None


@dataclass(frozen=True, slots=True)
class NewStudentAccount:
    """A student account to create, or an imported (unregistered) one to activate."""

    user_id: UUID
    activates_import: bool
    login: str
    password_hash: str
    first_name: str
    last_name: str
    middle_name: str | None
    recovery_email: str
    verified_at: datetime
    emis_student_id: int
    emis_vault_ref: UUID
    locale: str


# - - - Pending flows kept in Redis (30 minutes) - - -


class PendingRegistration(BaseModel):
    """Registration in progress: nothing is stored in the database yet."""

    emis_login: str
    password_enc: str
    token_enc: str
    profile: EmisProfile
    subjects: list[EmisSubject]
    import_user_id: UUID | None = None
    import_needs_confirmation: bool = False
    login: str
    email: str | None = None
    locale: str = "ru"


class PendingReclaim(BaseModel):
    """Reclaim in progress: EMIS credentials were checked, the email is not."""

    user_id: UUID
    emis_login: str
    password_enc: str
    token_enc: str
    email: str | None = None
    locale: str = "ru"
