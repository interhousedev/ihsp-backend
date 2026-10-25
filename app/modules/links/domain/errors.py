"""Errors of the links module."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    ValidationFailedError,
)


class BlockedUrlError(ValidationFailedError):
    """The URL is malformed, uses a forbidden scheme or points to a blocked domain."""

    code = "links/blocked-url"
    message_key = "links-blocked-url"


class InvalidLinkTargetError(ValidationFailedError):
    """The request does not name exactly the target its kind needs."""

    code = "links/invalid-target"
    message_key = "links-invalid-target"


class FileNotReadyError(ValidationFailedError):
    """The file is not ready, or it is not the caller's file."""

    code = "links/file-not-ready"
    message_key = "links-file-not-ready"


class InvalidExpiryError(ValidationFailedError):
    """The share expiry date is not in the future."""

    code = "links/invalid-expiry"
    message_key = "links-invalid-expiry"


class LessonMismatchError(ValidationFailedError):
    """An extra lesson is not the same subject on the same date."""

    code = "links/lesson-mismatch"
    message_key = "links-lesson-mismatch"


class LinkNotFoundError(NotFoundError):
    """No such link, or it is not visible to the caller."""

    code = "links/not-found"
    message_key = "links-not-found"


class LinkGoneError(GoneError):
    """The link was deleted, revoked or has expired."""

    code = "links/gone"
    message_key = "links-gone"


class LinkDisabledError(GoneError):
    """Administration disabled the link."""

    code = "links/disabled"
    message_key = "links-disabled"


class ShareNotAllowedError(ForbiddenError):
    """The caller cannot share this chat or set."""

    code = "links/share-not-allowed"
    message_key = "links-share-not-allowed"


class NotTeachingSubjectError(ForbiddenError):
    """The teacher has no lessons of the subject (for the group, if one is named)."""

    code = "links/not-teaching-subject"
    message_key = "links-not-teaching-subject"


class ResourceForbiddenError(ForbiddenError):
    """The caller may not add, see or change resources of this lesson."""

    code = "links/resource-forbidden"
    message_key = "links-resource-forbidden"


class LessonWindowClosedError(ForbiddenError):
    """Students attach files only from 7 days before to 14 days after a lesson."""

    code = "links/lesson-window-closed"
    message_key = "links-lesson-window-closed"


class SlugsExhaustedError(ConflictError):
    """No free short ID was found after many attempts."""

    code = "links/slug-exhausted"
    message_key = "links-slug-exhausted"


class SlugTakenError(Exception):
    """Raised by a repository when the slug is already used; handled by retrying."""
