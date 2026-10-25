"""Base error types shared by all modules."""

from typing import Any, ClassVar


class BaseError(Exception):
    """Expected application error with a stable code and an i18n message key."""

    code: ClassVar[str] = "common/internal"
    status: ClassVar[int] = 500
    message_key: ClassVar[str] = "error-internal"

    def __init__(
        self,
        *,
        params: dict[str, Any] | None = None,
        support_details: str | None = None,
        notify_user: bool = True,
    ) -> None:
        """Store i18n params for the user message and details for support."""
        self.params = params or {}
        self.support_details = support_details or self.code
        self.notify_user = notify_user
        super().__init__(self.support_details)


class NotFoundError(BaseError):
    """Entity does not exist or is not visible to the actor."""

    code = "common/not-found"
    status = 404
    message_key = "error-not-found"


class ForbiddenError(BaseError):
    """Actor lacks permission."""

    code = "common/forbidden"
    status = 403
    message_key = "error-forbidden"


class UnauthorizedError(BaseError):
    """Missing or invalid credentials."""

    code = "auth/unauthorized"
    status = 401
    message_key = "error-unauthorized"


class ConflictError(BaseError):
    """Stale version or conflicting state."""

    code = "common/conflict"
    status = 409
    message_key = "error-conflict"


class ValidationFailedError(BaseError):
    """Input is valid JSON but breaks a business rule."""

    code = "common/validation"
    status = 422
    message_key = "error-validation"


class RateLimitedError(BaseError):
    """Too many requests for this action."""

    code = "common/rate-limited"
    status = 429
    message_key = "error-rate-limited"


class GoneError(BaseError):
    """The resource existed but was removed, revoked or expired."""

    code = "common/gone"
    status = 410
    message_key = "error-gone"
