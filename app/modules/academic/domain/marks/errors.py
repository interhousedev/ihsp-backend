"""Errors of the student-facing marks views and the sync controls."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


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


class SyncRunNotFoundError(NotFoundError):
    """No EMIS sync run has this id."""

    code = "academic/sync-run-not-found"
    message_key = "academic-sync-run-not-found"


class SyncNotRunningError(ConflictError):
    """The sync (run or student) is not running, so it cannot be stopped."""

    code = "academic/sync-not-running"
    message_key = "academic-sync-not-running"


class InvalidWhatIfError(ValidationFailedError):
    """A hypothetical mark is not ``<type>:<2..5>`` or there are too many."""

    code = "academic/invalid-what-if"
    message_key = "academic-invalid-what-if"


class NotHeadStudentError(ForbiddenError):
    """The caller is not the head student of their group."""

    code = "academic/not-head-student"
    message_key = "academic-not-head-student"
