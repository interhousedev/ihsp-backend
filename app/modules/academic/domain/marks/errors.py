"""Errors of the student-facing marks views and the sync controls."""

from app.shared.base_error import ConflictError, NotFoundError, ValidationFailedError


class StudentNotFoundError(NotFoundError):
    """The user has no student record."""

    code = "academic/student-not-found"
    message_key = "academic-student-not-found"


class SubjectNotFoundError(NotFoundError):
    """The subject does not exist or is not in the student's curriculum."""

    code = "academic/subject-not-found"
    message_key = "academic-subject-not-found"


class SyncAlreadyRunningError(ConflictError):
    """An EMIS sync run is already in progress."""

    code = "academic/sync-running"
    message_key = "academic-sync-running"


class InvalidWhatIfError(ValidationFailedError):
    """A hypothetical mark is not ``<type>:<2..5>`` or there are too many."""

    code = "academic/invalid-what-if"
    message_key = "academic-invalid-what-if"
