"""Errors of the posts module."""

from app.shared.base_error import (
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


class PostNotFoundError(NotFoundError):
    """No post with this id."""

    code = "posts/not-found"
    message_key = "posts-not-found"


class InvalidPostError(ValidationFailedError):
    """A field breaks a rule; params: field, reason."""

    code = "posts/invalid"
    message_key = "posts-invalid"


class SlugTakenError(ConflictError):
    """Another post has this slug."""

    code = "posts/slug-taken"
    message_key = "posts-slug-taken"


class RootProtectedError(ConflictError):
    """The root post cannot be deleted or moved."""

    code = "posts/root-protected"
    message_key = "posts-root-protected"


class HasChildrenError(ConflictError):
    """The post has children; delete them first or pass cascade=true."""

    code = "posts/has-children"
    message_key = "posts-has-children"


class CycleError(ValidationFailedError):
    """The new parent is the post itself or one of its descendants."""

    code = "posts/cycle"
    message_key = "posts-cycle"


class ReorderMismatchError(ValidationFailedError):
    """The ids are not exactly the children of the parent."""

    code = "posts/reorder-mismatch"
    message_key = "posts-reorder-mismatch"


class GuestLimitError(RateLimitedError):
    """A guest asked too many questions (per minute or per day)."""

    code = "posts/guest-limit"
    message_key = "posts-guest-limit"


class GuestBusyError(RateLimitedError):
    """The guest assistant reached its global daily ceiling (all guests together)."""

    code = "posts/guest-busy"
    message_key = "posts-guest-busy"
