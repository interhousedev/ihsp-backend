"""Errors of the reader state area: progress, annotations, plans, lesson links."""

from app.shared.base_error import NotFoundError, ValidationFailedError


class InvalidLocatorError(ValidationFailedError):
    """The reading position does not fit the file format."""

    code = "library/invalid-locator"
    message_key = "library-invalid-locator"


class InvalidProgressError(ValidationFailedError):
    """The progress percentage is not a number from 0 to 100."""

    code = "library/invalid-progress"
    message_key = "library-invalid-progress"


class InvalidAnnotationError(ValidationFailedError):
    """A quote or a note is too long (`params.field`, `params.max`)."""

    code = "library/invalid-annotation"
    message_key = "library-invalid-annotation"


class SyncTooLargeError(ValidationFailedError):
    """More changes in one annotation sync than the server accepts."""

    code = "library/sync-too-large"
    message_key = "library-sync-too-large"


class InvalidBookPlanError(ValidationFailedError):
    """A book plan section is wrong (`params.field`, `params.n`)."""

    code = "library/plan-invalid"
    message_key = "library-plan-invalid"


class InvalidLessonRefError(ValidationFailedError):
    """A lesson link to a book is wrong or there are too many of them."""

    code = "library/refs-invalid"
    message_key = "library-refs-invalid"


class LessonNotFoundError(NotFoundError):
    """The lesson is missing or the caller has nothing to do with it."""

    code = "library/lesson-not-found"
    message_key = "library-lesson-not-found"


class FileNotInItemError(ValidationFailedError):
    """The file id is not one of the files of the item."""

    code = "library/invalid-file"
    message_key = "library-invalid-file"


class SubjectNotFoundError(NotFoundError):
    """The subject of a book plan does not exist."""

    code = "library/subject-not-found"
    message_key = "library-subject-not-found"
