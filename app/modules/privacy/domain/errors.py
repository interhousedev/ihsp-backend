"""Errors of the privacy module."""

from app.shared.base_error import ConflictError, NotFoundError, RateLimitedError


class ErasureAlreadyRequestedError(ConflictError):
    """An erasure request is already waiting for review or running."""

    code = "privacy/erasure-already-requested"
    message_key = "privacy-erasure-already-requested"


class ErasureRequestNotFoundError(NotFoundError):
    """No such erasure request."""

    code = "privacy/erasure-request-not-found"
    message_key = "privacy-erasure-request-not-found"


class ErasureNotPendingError(ConflictError):
    """The request was already decided."""

    code = "privacy/erasure-not-pending"
    message_key = "privacy-erasure-not-pending"


class ExportRateLimitedError(RateLimitedError):
    """One export per 24 hours (params: retry_after in seconds)."""

    code = "privacy/export-rate-limited"
    message_key = "privacy-export-rate-limited"


class ExportNotFoundError(NotFoundError):
    """The export does not exist, is not the caller's, is not ready or expired."""

    code = "privacy/export-not-found"
    message_key = "privacy-export-not-found"
