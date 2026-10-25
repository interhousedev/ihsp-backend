"""Errors of the UniLibrary area beyond those of doc § 7.4."""

from app.shared.base_error import ConflictError, NotFoundError, ValidationFailedError


class ExternalSyncUnavailableError(ConflictError):
    """Dry run or run of a feed: the sync is not built in this release."""

    code = "library/external-sync-unavailable"
    status = 409
    message_key = "library-external-sync-unavailable"


class FeedNotFoundError(NotFoundError):
    """No feed with this id."""

    code = "library/feed-not-found"
    message_key = "library-feed-not-found"


class FieldMapInvalidError(ValidationFailedError):
    """The field map names subjects that do not exist (`params.subject_ids`)."""

    code = "library/field-map-invalid"
    message_key = "library-field-map-invalid"
