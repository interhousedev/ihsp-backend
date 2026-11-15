"""Expected failures of registration, reclaim, EMIS password update and deletion."""

from collections.abc import Iterator
from contextlib import contextmanager

from app.modules.identity.application.register_models import (
    CredentialNotFoundError,
    CredentialStoreError,
    EmisAuthError,
    EmisFileGoneError,
    EmisFileRetryError,
    EmisPausedError,
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
    EmisFileNotFound,
    EmisFileRetryLater,
    EmisPaused,
    EmisUnavailable,
)

import structlog

log = structlog.get_logger(__name__)


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


class ConsentRequiredError(ValidationFailedError):
    """Registration lacks the current version of every published legal document."""

    code = "legal/consent-required"
    message_key = "legal-consent-required"


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


class WrongEmisPasswordError(ForbiddenError):
    """The current EMIS password is wrong (403, so the web client stays logged in)."""

    code = "id/wrong-emis-password"
    message_key = "id-wrong-emis-password"


class EmisNewPasswordRejectedError(ValidationFailedError):
    """EMIS refused the new password, for example because it is too weak."""

    code = "id/emis-new-password-rejected"
    message_key = "id-emis-new-password-rejected"


class DeleteForbiddenError(ForbiddenError):
    """Only student accounts can delete themselves."""

    code = "id/delete-forbidden"
    message_key = "id-delete-forbidden"


def _unavailable_from(exc: EmisRequestError) -> EmisUnavailable:
    """Log the upstream reason and build the 503 carrying it.

    The client already logged every failed attempt (``emis_request_failed``) and the
    HTTP edge logs the ``domain_error``; this line only links them, so info level.
    """
    log.info(
        "emis_upstream_failed",
        source="emis",
        reason=exc.reason,
        detail=str(exc),
        status=exc.status,
        exc_class=type(exc).__name__,
        error_id=exc.error_id,
    )
    params: dict[str, str | int] = {"reason": exc.reason}
    if exc.status is not None:
        params["upstream_status"] = exc.status
    return EmisUnavailable(
        params=params,
        support_details=(
            f"EMIS: {exc} [reason={exc.reason} upstream_status={exc.status} "
            f"error_id={exc.error_id}]"
        ),
    )


def _file_error(exc: EmisFileGoneError | EmisFileRetryError) -> Exception:
    if isinstance(exc, EmisFileGoneError):
        return EmisFileNotFound(
            support_details=f"EMIS file is gone (HTTP {exc.status})"
        )
    return EmisFileRetryLater(support_details=f"EMIS file: {exc}")


@contextmanager
def emis_errors() -> Iterator[None]:
    """Map EMIS and Vault port errors to the contract errors (401 / 503).

    The real reason is logged here: the 503 body is generic, so without this line the
    upstream status (EMIS HTTP 404, 413, a Vault seal) is lost in production.
    """
    try:
        yield
    except EmisAuthError as exc:
        raise EmisAuthFailed(support_details="EMIS rejected the credentials") from exc
    except EmisPausedError as exc:
        raise EmisPaused(
            retry_after=exc.retry_after, support_details="EMIS asked for a pause"
        ) from exc
    except (EmisFileGoneError, EmisFileRetryError) as exc:
        raise _file_error(exc) from exc
    except EmisRequestError as exc:
        raise _unavailable_from(exc) from exc
    except CredentialNotFoundError as exc:
        raise EmisCredentialsMissing(support_details="Vault secret is missing") from exc
    except CredentialStoreError as exc:
        log.warning("emis_upstream_failed", source="vault", reason=str(exc))
        raise EmisUnavailable(
            params={"reason": "vault_unavailable"},
            support_details=f"Vault: {exc}",
        ) from exc
