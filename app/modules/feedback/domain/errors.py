"""Errors of the feedback module."""

from app.shared.base_error import (
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


class FeedbackNotFoundError(NotFoundError):
    """The feedback does not exist or belongs to someone else."""

    code = "feedback/not-found"
    message_key = "feedback-not-found"


class FeedbackInvalidError(ValidationFailedError):
    """A field is empty, too long or not one of the allowed values. Params: field."""

    code = "feedback/invalid"
    message_key = "feedback-invalid"


class FeedbackAttachmentError(ValidationFailedError):
    """An attachment is missing, not the caller's, not ready or of a wrong type.

    Params: file_id, reason (not_found, not_owner, not_ready, type, too_many).
    """

    code = "feedback/attachment-invalid"
    message_key = "feedback-attachment-invalid"


class FeedbackRateLimitedError(RateLimitedError):
    """More than 10 feedback items today (HTTP 429). Params: retry_after."""

    code = "feedback/rate-limited"
    message_key = "feedback-rate-limited"
