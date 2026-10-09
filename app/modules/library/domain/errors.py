"""Errors of the library module (doc § 7.4). Codes are the `problem+json` types."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)


class ItemNotFoundError(NotFoundError):
    """Item missing or not visible to the caller (never a 403 for hidden items)."""

    code = "library/not-found"
    message_key = "library-not-found"


class ListNotFoundError(NotFoundError):
    """Reading list missing or not visible."""

    code = "library/list-not-found"
    message_key = "library-list-not-found"


class TopicNotFoundError(NotFoundError):
    """Topic missing."""

    code = "library/topic-not-found"
    message_key = "library-topic-not-found"


class CollectionNotFoundError(NotFoundError):
    """Collection missing or not published."""

    code = "library/collection-not-found"
    message_key = "library-collection-not-found"


class ReportNotFoundError(NotFoundError):
    """Report missing."""

    code = "library/report-not-found"
    message_key = "library-report-not-found"


class AnnotationNotFoundError(NotFoundError):
    """Annotation missing or not the caller's."""

    code = "library/annotation-not-found"
    message_key = "library-annotation-not-found"


class SuggestionNotFoundError(NotFoundError):
    """Book suggestion missing."""

    code = "library/suggestion-not-found"
    message_key = "library-suggestion-not-found"


class NotSupportedError(ConflictError):
    """Reader, file, progress, annotation or notebook action on a UniLibrary item."""

    code = "library/not-supported"
    status = 409
    message_key = "library-not-supported"


class RightsIncompleteError(ValidationFailedError):
    """Publishing a book without a recorded basis (`params.missing[]`)."""

    code = "library/rights-incomplete"
    message_key = "library-rights-incomplete"


class VisibilityConflictError(ValidationFailedError):
    """`public` with a rights class or kind that forbids it."""

    code = "library/visibility-conflict"
    message_key = "library-visibility-conflict"


class TextUnavailableError(ConflictError):
    """No extracted text (scans, or the text is not ready yet)."""

    code = "library/text-unavailable"
    message_key = "library-text-unavailable"


class ListTooLongError(ValidationFailedError):
    """More entries than `LIBRARY__LIST_MAX_ITEMS`."""

    code = "library/list-too-long"
    message_key = "library-list-too-long"


class OwnItemError(ForbiddenError):
    """A librarian approving their own upload."""

    code = "library/own-item"
    message_key = "library-own-item"


class NotEditableError(ConflictError):
    """Editing in a state that forbids it."""

    code = "library/not-editable"
    message_key = "library-not-editable"


class InvalidTransitionError(ConflictError):
    """The requested status change is not allowed from the current status."""

    code = "library/invalid-transition"
    message_key = "library-invalid-transition"


class FileTooLargeError(BaseError):
    """File over the limit of its role (HTTP 413)."""

    code = "library/file-too-large"
    status = 413
    message_key = "library-file-too-large"


class TooManyPagesError(ValidationFailedError):
    """More pages than a student material may have."""

    code = "library/too-many-pages"
    message_key = "library-too-many-pages"


class DuplicateItemError(ConflictError):
    """Same file or text already in the library (`params.item_id` when visible)."""

    code = "library/duplicate"
    message_key = "library-duplicate"


class LibraryRateLimitedError(RateLimitedError):
    """Upload, report or search limit (`params: {action, limit, resets_at}`)."""

    code = "library/rate-limited"
    message_key = "library-rate-limited"


class UploadBannedError(ForbiddenError):
    """The user is banned from uploading (`params.until`)."""

    code = "library/banned"
    message_key = "library-banned"


class AttestationRequiredError(ValidationFailedError):
    """The uploader did not tick the attestation."""

    code = "library/attestation-required"
    message_key = "library-attestation-required"


class ReasonRequiredError(ValidationFailedError):
    """A decision other than approve needs a reason."""

    code = "library/reason-required"
    message_key = "library-reason-required"


class NoFilesError(ValidationFailedError):
    """Submitting a material that has neither a file nor a text body."""

    code = "library/no-files"
    message_key = "library-no-files"


class ExternalDisabledError(NotFoundError):
    """The UniLibrary flag is off."""

    code = "library/external-disabled"
    message_key = "library-external-disabled"


class ExternalUnavailableError(BaseError):
    """UniLibrary breaker open and nothing cached (`params.retry_after`)."""

    code = "library/external-unavailable"
    status = 503
    message_key = "library-external-unavailable"
