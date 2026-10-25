"""Errors of assessments."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


class AssessmentNotFoundError(NotFoundError):
    """The assessment does not exist or is not visible to the caller."""

    code = "academic/assessment-not-found"
    message_key = "academic-assessment-not-found"


class NotAssessmentTeacherError(ForbiddenError):
    """Only a teacher of the subject in that group, or Administration, may do this."""

    code = "academic/not-assessment-teacher"
    message_key = "academic-not-assessment-teacher"


class NotHeadStudentError(ForbiddenError):
    """Only the head student of a group may propose a control for it."""

    code = "academic/not-head-student"
    message_key = "academic-not-head-student"


class AssessmentSubjectNotFoundError(NotFoundError):
    """The subject of the assessment does not exist."""

    code = "academic/assessment-subject-not-found"
    message_key = "academic-assessment-subject-not-found"


class InvalidAssessmentError(ValidationFailedError):
    """The assessment breaks a rule: no audience, a group that does not exist, ..."""

    code = "academic/invalid-assessment"
    message_key = "academic-invalid-assessment"


class AssessmentExistsError(ConflictError):
    """A control of this subject, kind and date is already listed for the group."""

    code = "academic/assessment-exists"
    message_key = "academic-assessment-exists"
