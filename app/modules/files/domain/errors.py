"""Typed errors of the files module."""

from app.shared.base_error import (
    ConflictError,
    GoneError,
    NotFoundError,
    ValidationFailedError,
)


class QuotaExceededError(ValidationFailedError):
    """The upload would exceed the owner's storage quota."""

    code = "files/quota-exceeded"
    status = 413
    message_key = "files-quota-exceeded"


class FileTooLargeError(ValidationFailedError):
    """The file is bigger than the per-file limit."""

    code = "files/too-large"
    status = 413
    message_key = "files-too-large"


class TypeNotAllowedError(ValidationFailedError):
    """The file type is not allowed for this purpose."""

    code = "files/type-not-allowed"
    status = 415
    message_key = "files-type-not-allowed"


class InvalidFileNameError(ValidationFailedError):
    """The file name is empty or too long."""

    code = "files/invalid-name"
    message_key = "files-invalid-name"


class InvalidChecksumError(ValidationFailedError):
    """The declared SHA-256 is not a base64 digest of 32 bytes."""

    code = "files/invalid-checksum"
    message_key = "files-invalid-checksum"


class InvalidSizeError(ValidationFailedError):
    """The declared size is not a positive number."""

    code = "files/invalid-size"
    message_key = "files-invalid-size"


class UploadMissingError(ConflictError):
    """complete was called but the object is not in storage."""

    code = "files/upload-missing"
    message_key = "files-upload-missing"


class StoredFileNotFoundError(NotFoundError):
    """No such file, or it is not visible to the caller."""

    code = "files/not-found"
    message_key = "files-not-found"


class FileDeletedError(GoneError):
    """The file was deleted (by its owner or by cleanup)."""

    code = "files/deleted"
    message_key = "files-deleted"


class FileNotReadyError(ConflictError):
    """The file was not uploaded yet, or was rejected."""

    code = "files/not-ready"
    message_key = "files-not-ready"


class NoTextError(NotFoundError):
    """The file has no extracted text."""

    code = "files/no-text"
    message_key = "files-no-text"


class TextPageNotFoundError(NotFoundError):
    """The requested page of the extracted text does not exist."""

    code = "files/page-not-found"
    message_key = "files-page-not-found"


class TextExtractionError(Exception):
    """A text extractor could not read the file (never shown to users)."""
