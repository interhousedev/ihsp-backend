"""Errors of the legal module."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


class LegalInvalidError(ValidationFailedError):
    """A kind or a locale is unknown. Params: field."""

    code = "legal/invalid"
    message_key = "legal-invalid"


class LegalIncompleteError(ValidationFailedError):
    """The draft lacks texts to publish. Params: fields."""

    code = "legal/incomplete"
    message_key = "legal-incomplete"


class LegalNoDraftError(ValidationFailedError):
    """There is no draft of the kind to publish. Params: kind."""

    code = "legal/no-draft"
    message_key = "legal-no-draft"


class LegalStaleVersionError(ConflictError):
    """The accepted version is not the current one. Params: kind, current."""

    code = "legal/stale-version"
    message_key = "legal-stale-version"


class LegalNotFoundError(NotFoundError):
    """No published document of the kind. Params: kind."""

    code = "legal/not-found"
    message_key = "legal-not-found"


class LegalAcceptanceRequiredError(ForbiddenError):
    """The user has not accepted the current documents. Params: kinds."""

    code = "legal/acceptance-required"
    message_key = "legal-acceptance-required"
