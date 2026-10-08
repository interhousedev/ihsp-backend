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


class AiProviderError(BaseError):
    """The language model provider failed or is unavailable."""

    code = "ai/provider-error"
    status = 503
    message_key = "ai-provider-error"


class AiLimitReachedError(RateLimitedError):
    """The session or daily token budget is used up (params: scope, resets_at)."""

    code = "ai/limit-reached"
    status = 429
    message_key = "ai-limit-reached"


class ChatNotFoundError(NotFoundError):
    """The chat does not exist, is deleted or belongs to someone else."""

    code = "ai/chat-not-found"
    message_key = "ai-chat-not-found"


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
    """The user's roles do not allow this assistant."""

    code = "ai/wrong-assistant"
    message_key = "ai-wrong-assistant"


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
