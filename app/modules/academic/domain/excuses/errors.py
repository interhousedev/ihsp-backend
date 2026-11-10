"""Errors of excuses."""

from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


class ExcuseNotFoundError(NotFoundError):
    """The excuse does not exist or is not visible to the caller."""

    code = "academic.excuse_not_found"
    message_key = "excuse-not-found"


class ExcuseTemplateNotFoundError(ValidationFailedError):
    """The reason template is unknown or switched off."""

    code = "academic.excuse_template_not_found"
    message_key = "excuse-template-not-found"


class ExcuseNotPendingError(ConflictError):
    """The excuse was already decided or cancelled."""

    code = "academic.excuse_not_pending"
    message_key = "excuse-not-pending"


class ExcuseNotApprovedError(ConflictError):
    """Only an approved excuse can be ended or revoked."""

    code = "academic.excuse_not_approved"
    message_key = "excuse-not-approved"


class ExcuseNotYoursError(ForbiddenError):
    """Only the curator of the student's group may exclude the student."""

    code = "academic.excuse_not_curator"
    message_key = "excuse-not-curator"


class ExcuseInvalidError(ValidationFailedError):
    """Dates, text or targets of the excuse break a rule."""

    code = "academic.excuse_invalid"
    message_key = "excuse-invalid"


class ExcuseDocumentRequiredError(ValidationFailedError):
    """The reason needs a document and the request has no attachment."""

    code = "academic.excuse_document_required"
    message_key = "excuse-document-required"


class ExcuseAttachmentError(ValidationFailedError):
    """An attachment is not the author's, not ready, or of a wrong type."""

    code = "academic.excuse_attachment_invalid"
    message_key = "excuse-attachment-invalid"


class AttendanceExcusedLockedError(ConflictError):
    """An officially excused student cannot be marked present or late."""

    code = "academic.attendance_excused_locked"
    message_key = "attendance-excused-locked"
