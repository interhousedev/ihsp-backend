"""Errors of the AI assistants."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from app.shared.contracts import ai as ai_contract

# The provider errors live in the contract, so that other modules can raise them.
AiProviderError = ai_contract.AiProviderError
AiInvalidOutputError = ai_contract.AiInvalidOutputError


class AiLimitReachedError(RateLimitedError):
    """The session or daily token budget is used up (params: scope, resets_at)."""

    code = "ai/limit-reached"
    status = 429
    message_key = "ai-limit-reached"


class AiSmartLimitReachedError(RateLimitedError):
    """The smart tier's requests of the week are used up (params: limit, date)."""

    code = "ai/smart-weekly-limit"
    status = 429
    message_key = "ai-smart-weekly-limit"


class ChatNotFoundError(NotFoundError):
    """The chat does not exist, is deleted or belongs to someone else."""

    code = "ai/chat-not-found"
    message_key = "ai-chat-not-found"


class MessageNotFoundError(NotFoundError):
    """The chat has no message with this sequence number."""

    code = "ai/message-not-found"
    message_key = "ai-message-not-found"


class FeedbackNotAllowedError(ValidationFailedError):
    """Only the assistant's own messages can be rated."""

    code = "ai/feedback-not-allowed"
    message_key = "ai-feedback-not-allowed"


class ApprovalPendingError(ConflictError):
    """An approval card still waits, so the answer cannot be generated again."""

    code = "ai/approval-pending"
    message_key = "ai-approval-pending"


class NothingToRegenerateError(ConflictError):
    """The chat has no user message to answer again."""

    code = "ai/nothing-to-regenerate"
    message_key = "ai-nothing-to-regenerate"


class ToolCallNotFoundError(NotFoundError):
    """The chat has no tool call with this id."""

    code = "ai/tool-call-not-found"
    message_key = "ai-tool-call-not-found"


class ToolCallNotPendingError(ConflictError):
    """The tool call was already decided, superseded or is running."""

    code = "ai/tool-call-not-pending"
    message_key = "ai-tool-call-not-pending"


class ToolCallExpiredError(GoneError):
    """The approval card expired after 24 hours."""

    code = "ai/tool-call-expired"
    message_key = "ai-tool-call-expired"


class TurnInProgressError(ConflictError):
    """Another request is still working on this chat."""

    code = "ai/turn-in-progress"
    message_key = "ai-turn-in-progress"


class WrongAssistantError(ForbiddenError):
    """The user's roles (or course permissions) do not allow this assistant."""

    code = "ai/wrong-assistant"
    message_key = "ai-wrong-assistant"


class AuthorUnavailableError(NotFoundError):
    """The course author assistant is switched off or not wired in this process."""

    code = "ai/feature-disabled"
    message_key = "ai-feature-disabled"


class CourseRequiredError(ValidationFailedError):
    """The course author assistant works on one course: `course_id` is missing."""

    code = "ai/course-required"
    message_key = "ai-course-required"


class AttachmentInvalidError(ValidationFailedError):
    """An attached file is missing, not the user's own or not ready."""

    code = "ai/attachment-invalid"
    message_key = "ai-attachment-invalid"


class ToolArgumentsError(ValidationFailedError):
    """The model sent arguments that break the tool's schema or rules."""

    code = "ai/tool-arguments"
    message_key = "ai-tool-arguments"


class ToolFailedError(BaseError):
    """A tool could not do what was asked (the message goes back to the model)."""

    code = "ai/tool-failed"
    status = 422
    message_key = "ai-tool-failed"
