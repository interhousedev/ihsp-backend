"""Expected failures of registration, reclaim, EMIS password update and deletion."""

from collections.abc import Iterator
from contextlib import contextmanager

from app.modules.identity.application.register_models import (
    CredentialNotFoundError,
    CredentialStoreError,
    EmisAuthError,
    EmisRequestError,
)
from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    ValidationFailedError,
)
from app.shared.contracts.emis import (
    EmisAuthFailed,
    EmisCredentialsMissing,
    EmisUnavailable,
)


class WrongInstitutionError(ForbiddenError):
    """The EMIS profile belongs to another institution (ID-2)."""

    code = "id/wrong-institution"
    message_key = "id-wrong-institution"


class EmisAlreadyLinkedError(ConflictError):
    """The EMIS profile already has an IHSP account (ID-3)."""

    code = "id/emis-already-linked"
    message_key = "id-emis-already-linked"


class RegistrationExpiredError(GoneError):
    """The registration or reclaim token is unknown or older than 30 minutes."""

    code = "id/registration-expired"
    message_key = "id-registration-expired"


class EmailInUseError(ConflictError):
    """The email belongs to another account."""

    code = "id/email-in-use"
    message_key = "id-email-in-use"


class EmailNotSetError(ValidationFailedError):
    """No email code was requested for this registration yet."""

    code = "id/email-not-set"
    message_key = "id-email-not-set"


class OtpCodeInvalidError(ValidationFailedError):
    """The code is wrong, expired or used up (3 attempts)."""

    code = "id/code-invalid"
    message_key = "id-code-invalid"


class ImportMatchUnconfirmedError(ConflictError):
    """The student must confirm that the imported record is theirs."""

    code = "id/import-match-unconfirmed"
    message_key = "id-import-match-unconfirmed"


class WeakPasswordError(ValidationFailedError):
    """The password breaks the policy; ``params.errors`` lists the i18n keys."""

    code = "id/password-weak"
    message_key = "id-password-weak"


class UserNotFoundError(NotFoundError):
    """No account is linked to these EMIS credentials."""

    code = "id/user-not-found"
    message_key = "id-user-not-found"


class ReclaimForbiddenError(ForbiddenError):
    """The account cannot be reclaimed (Administration role, blocked)."""

    code = "id/reclaim-forbidden"
    message_key = "id-reclaim-forbidden"


class NoEmisLinkError(ConflictError):
    """The user has no EMIS link to update."""

    code = "id/no-emis-link"
    message_key = "id-no-emis-link"


class EmisProfileMismatchError(ConflictError):
    """The EMIS credentials belong to a different EMIS profile."""

    code = "id/emis-profile-mismatch"
    message_key = "id-emis-profile-mismatch"


class WrongPasswordError(ForbiddenError):
    """The current password is wrong (403, so the web client stays logged in)."""

    code = "id/wrong-password"
    message_key = "id-wrong-password"


class DeleteForbiddenError(ForbiddenError):
    """Only student accounts can delete themselves."""

    code = "id/delete-forbidden"
    message_key = "id-delete-forbidden"


@contextmanager
def emis_errors() -> Iterator[None]:
    """Map EMIS and Vault port errors to the contract errors (401 / 503)."""
    try:
        yield
    except EmisAuthError as exc:
        raise EmisAuthFailed(support_details="EMIS rejected the credentials") from exc
    except EmisRequestError as exc:
        raise EmisUnavailable(support_details=f"EMIS: {exc}") from exc
    except CredentialNotFoundError as exc:
        raise EmisCredentialsMissing(support_details="Vault secret is missing") from exc
    except CredentialStoreError as exc:
        raise EmisUnavailable(support_details=f"Vault: {exc}") from exc
