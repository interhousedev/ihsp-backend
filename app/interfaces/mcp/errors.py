"""Errors raised by the MCP interface (mapped to tool errors in guard.py)."""

from app.shared.base_error import (
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    ValidationFailedError,
)


class McpUnauthenticatedError(UnauthorizedError):
    """The call carries no authenticated connector or OAuth token."""

    code = "mcp/unauthenticated"
    message_key = "mcp-unauthenticated"


class McpScopeError(ForbiddenError):
    """The connector was not granted the scope the tool needs."""

    code = "mcp/insufficient-scope"
    message_key = "mcp-insufficient-scope"


class McpRateLimitedError(RateLimitedError):
    """More than the allowed number of calls in one minute."""

    code = "mcp/rate-limited"
    message_key = "mcp-rate-limited"


class McpCourseNotAllowedError(ForbiddenError):
    """The connector is limited to other courses."""

    code = "mcp/course-not-allowed"
    message_key = "mcp-course-not-allowed"


class McpToolNotAllowedError(ForbiddenError):
    """The Administration server only forwards read-only tools."""

    code = "mcp/tool-not-allowed"
    message_key = "mcp-tool-not-allowed"


class McpFileAccessError(ForbiddenError):
    """The file is missing, not ready or not available to the caller."""

    code = "mcp/file-not-accessible"
    message_key = "mcp-file-not-accessible"


class McpNotOwnerError(ForbiddenError):
    """The caller does not own the flash card set."""

    code = "mcp/not-owner"
    message_key = "mcp-not-owner"


class McpNotFoundError(NotFoundError):
    """The entity does not exist or is not visible to the caller."""

    code = "mcp/not-found"
    message_key = "mcp-not-found"


class McpInvalidInputError(ValidationFailedError):
    """Arguments are well formed but break a rule (params: reason)."""

    code = "mcp/invalid-input"
    message_key = "mcp-invalid-input"


class McpRangeTooLongError(ValidationFailedError):
    """The requested date range is longer than the limit (params: max_days)."""

    code = "mcp/range-too-long"
    message_key = "mcp-range-too-long"


class McpFileNoTextError(ValidationFailedError):
    """The file has no extracted text to read."""

    code = "mcp/file-no-text"
    message_key = "mcp-file-no-text"


class McpFileTooLargeError(ValidationFailedError):
    """The file text is larger than the assistant limit (params: max_bytes)."""

    code = "mcp/file-too-large"
    message_key = "mcp-file-too-large"
