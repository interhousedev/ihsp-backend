"""Typed errors of the AI review block."""

from app.shared.base_error import ConflictError, NotFoundError, ValidationFailedError


class AiReviewSessionNotFoundError(NotFoundError):
    """The review session does not exist or belongs to someone else."""

    code = "lms/ai-review-session-not-found"
    message_key = "lms-ai-review-session-not-found"


class AiReviewNoSubmissionsLeftError(ConflictError):
    """The student used every submission the block allows."""

    code = "lms/ai-review-no-submissions-left"
    message_key = "lms-ai-review-no-submissions-left"


class AiReviewClosedError(ConflictError):
    """The session already has its final review."""

    code = "lms/ai-review-closed"
    message_key = "lms-ai-review-closed"


class AiReviewFileRejectedError(ValidationFailedError):
    """A file is not the student's own upload or has a type the block refuses."""

    code = "lms/ai-review-file-rejected"
    message_key = "lms-ai-review-file-rejected"


class AiReviewUnavailableError(ConflictError):
    """The AI model is not configured in this process."""

    code = "lms/ai-review-unavailable"
    status = 503
    message_key = "lms-ai-review-unavailable"
