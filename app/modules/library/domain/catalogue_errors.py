"""Errors of the catalogue area on top of `domain/errors.py`."""

from app.shared.base_error import ForbiddenError, ValidationFailedError


class InvalidFileError(ValidationFailedError):
    """The file cannot be attached: unknown, not ready, not yours or the wrong kind."""

    code = "library/file-invalid"
    message_key = "library-file-invalid"


class InvalidReferenceError(ValidationFailedError):
    """A subject, topic or file named in the form does not exist."""

    code = "library/invalid-reference"
    message_key = "library-invalid-reference"


class DownloadNotAllowedError(ForbiddenError):
    """The rights basis of the book does not allow downloading its file."""

    code = "library/download-not-allowed"
    message_key = "library-download-not-allowed"


class ImportInvalidError(ValidationFailedError):
    """The CSV of a bulk import cannot be read (not a CSV, too big, no header)."""

    code = "library/import-invalid"
    message_key = "library-import-invalid"
