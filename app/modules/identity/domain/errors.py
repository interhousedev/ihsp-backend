"""Identity domain errors (stable codes, i18n keys in locales/*/id.json)."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    UnauthorizedError,
    ValidationFailedError,
)


class InvalidCredentialsError(UnauthorizedError):
    """Wrong login or password (also a blocked account, after the password check)."""

    code = "auth/invalid-credentials"
    status = 401
    message_key = "id-invalid-credentials"


class SecondFactorRequiredError(UnauthorizedError):
    """A one-time code is needed in addition to the password."""

    code = "auth/second-factor-required"
    status = 401
    message_key = "id-second-factor-required"


class AccountLockedError(BaseError):
    """Too many failed logins for this login and IP; try again later."""

    code = "auth/locked"
    status = 423
    message_key = "id-account-locked"


class RoleMissingError(ForbiddenError):
    """The account lacks the role the platform requires."""

    code = "auth/role-missing"
    message_key = "id-role-missing"


class OtpInvalidError(UnauthorizedError):
    """The one-time code is wrong, expired or used up."""

    code = "auth/otp-invalid"
    status = 401
    message_key = "id-otp-invalid"


class ChallengeUsedError(GoneError):
    """Hydra already handled this login, consent or logout challenge."""

    code = "auth/challenge-used"
    status = 410
    message_key = "id-challenge-used"


class InvalidChallengeError(NotFoundError):
    """Hydra does not know this challenge."""

    code = "auth/challenge-invalid"
    message_key = "id-challenge-invalid"


class TelegramLinkedElsewhereError(ConflictError):
    """The Telegram account is linked to another user."""

    code = "telegram/linked-elsewhere"
    status = 409
    message_key = "id-telegram-linked-elsewhere"


class AdminResetForbiddenError(ForbiddenError):
    """Administration accounts are reset by another Administration member only."""

    code = "id/admin-reset-forbidden"
    message_key = "id-admin-reset-forbidden"


class AdminTargetResetForbiddenError(ForbiddenError):
    """The link route does not issue links for Administration accounts."""

    code = "id/admin-target-reset-forbidden"
    message_key = "id-admin-target-reset-forbidden"


class AdminServerForbiddenError(ForbiddenError):
    """Dynamically registered, unverified clients may not use the admin server."""

    code = "id/admin-server-forbidden"
    message_key = "id-admin-server-forbidden"


class PasswordPolicyError(ValidationFailedError):
    """The new password breaks the policy; params.errors lists the rule keys."""

    code = "id/password-policy"
    message_key = "id-password-policy"


class EmailTakenError(ConflictError):
    """The email belongs to another account."""

    code = "id/email-taken"
    message_key = "id-email-taken"


class EmailLockedError(ValidationFailedError):
    """The email of an activated account cannot be edited by Administration."""

    code = "id/email-locked"
    message_key = "id-email-locked"


class OtpChannelMissingError(ValidationFailedError):
    """No channel is available to deliver a one-time code."""

    code = "id/otp-no-channel"
    message_key = "id-otp-no-channel"


class SelfActionForbiddenError(ForbiddenError):
    """An administrator cannot do this to their own account."""

    code = "id/self-action-forbidden"
    message_key = "id-self-action-forbidden"


class LmsAdminNeedsAdminError(ValidationFailedError):
    """`lms_admin` is an extra role of Administration: it needs `admin` as well."""

    code = "id/lms-admin-needs-admin"
    message_key = "id-lms-admin-needs-admin"


class CourseCreatorNotStaffError(ValidationFailedError):
    """Only a teacher or an administrator can be a course creator."""

    code = "id/course-creator-not-staff"
    message_key = "id-course-creator-not-staff"


class InvalidStatusError(ConflictError):
    """The account status does not allow this transition."""

    code = "id/invalid-status"
    message_key = "id-invalid-status"


class ActivationLinkInvalidError(GoneError):
    """The activation link is unknown, used or expired."""

    code = "id/activation-invalid"
    message_key = "id-activation-invalid"


class LoginTicketInvalidError(GoneError):
    """The one-time sign-in ticket of a registration or reset is unknown or used."""

    code = "id/login-ticket-invalid"
    message_key = "id-login-ticket-invalid"


class UserNotFoundError(NotFoundError):
    """No such user."""

    code = "id/user-not-found"
    message_key = "id-user-not-found"


class ConnectorInvalidError(ValidationFailedError):
    """The connector request breaks the rules of its server."""

    code = "id/connector-invalid"
    message_key = "id-connector-invalid"


class UnknownClientError(ValidationFailedError):
    """The OAuth client is not one of ours."""

    code = "id/unknown-client"
    message_key = "id-unknown-client"


class HydraUnavailableError(BaseError):
    """Ory Hydra did not answer or answered with an unexpected error."""

    code = "id/hydra-unavailable"
    status = 503
    message_key = "id-hydra-unavailable"


class EmailDeliveryError(BaseError):
    """The email could not be sent."""

    code = "id/email-unavailable"
    status = 503
    message_key = "id-email-unavailable"


class LoginTakenError(ConflictError):
    """The login belongs to another account."""

    code = "id/login-taken"
    message_key = "id-login-taken"


class PhotoEmptyError(ValidationFailedError):
    """The uploaded photo has no content."""

    code = "id/photo-empty"
    message_key = "id-photo-empty"


class PhotoTooLargeError(ValidationFailedError):
    """The photo is bigger than the limit; ``params.max_mb`` says how much."""

    code = "id/photo-too-large"
    status = 413
    message_key = "id-photo-too-large"


class PhotoTypeNotAllowedError(ValidationFailedError):
    """The photo is neither a JPEG nor a PNG image."""

    code = "id/photo-type-not-allowed"
    status = 422
    message_key = "id-photo-type-not-allowed"
