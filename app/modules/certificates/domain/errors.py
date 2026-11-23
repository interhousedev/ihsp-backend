"""Errors of the certificates module."""

from app.shared.base_error import (
    BaseError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailedError,
)


class CertificateTypeNotFoundError(NotFoundError):
    """The certificate type does not exist."""

    code = "certificate_type_not_found"
    message_key = "cert-type-not-found"


class CertificateTypeBuiltinError(ConflictError):
    """A built-in type cannot be deleted and keeps its code."""

    code = "certificate_type_builtin"
    message_key = "cert-type-builtin"


class CertificateTypeInUseError(ConflictError):
    """Entries use the type, so it cannot be deleted."""

    code = "certificate_type_in_use"
    message_key = "cert-type-in-use"


class CertificateTypeCodeTakenError(ConflictError):
    """Another type already has this code."""

    code = "certificate_type_code_taken"
    message_key = "cert-type-code-taken"


class CertificateEntryNotFoundError(NotFoundError):
    """The entry does not exist or belongs to someone else."""

    code = "certificate_entry_not_found"
    message_key = "cert-entry-not-found"


class CertificateFileNotFoundError(NotFoundError):
    """The file is not attached to the entry (or is not visible to the caller)."""

    code = "certificate_file_not_found"
    message_key = "cert-file-not-found"


class CertificateInvalidError(ValidationFailedError):
    """A value does not fit the type. Params: field, and min/max when they apply."""

    code = "certificate_invalid"
    message_key = "cert-invalid"


class NotCuratorError(ForbiddenError):
    """The caller does not curate the group (or any group)."""

    code = "certificate_not_curator"
    message_key = "cert-not-curator"


class CertificateDownloadError(BaseError):
    """A certificate PDF could not be downloaded (never shown to students)."""

    code = "certificate_download_failed"
    status = 502
    message_key = "cert-download-failed"


class UnsafeCertificateUrlError(CertificateDownloadError):
    """The URL is not an https address on the issuer's domain, or resolves inside."""

    code = "certificate_url_unsafe"
    status = 422
    message_key = "cert-url-unsafe"


class CustomFieldRequiredError(ValidationFailedError):
    """A required custom field of the type has no value. Params: field (its key)."""

    code = "certificate_custom_field_required"
    message_key = "cert-custom-field-required"


class CustomFieldInvalidError(ValidationFailedError):
    """A custom field value does not fit its kind or options. Params: field (key)."""

    code = "certificate_custom_field_invalid"
    message_key = "cert-custom-field-invalid"


class CourseCertificateForbiddenError(ForbiddenError):
    """The caller does not manage the certificates of the course."""

    code = "course_certificate_forbidden"
    message_key = "course-cert-forbidden"


class CourseCertificateNotFoundError(NotFoundError):
    """The certificate, template, partner or course does not exist (or is hidden)."""

    code = "course_certificate_not_found"
    message_key = "course-cert-not-found"


class CourseCertificateInvalidError(ValidationFailedError):
    """A setting, tier, layout or partner value is not valid. Params: field."""

    code = "course_certificate_invalid"
    message_key = "course-cert-invalid"


class CertificateUploadRejectedError(ValidationFailedError):
    """An uploaded image is not a PNG, JPEG or PDF, or is too large. Params: reason."""

    code = "course_certificate_upload_rejected"
    message_key = "course-cert-upload-rejected"


class CourseCertificateNotEligibleError(ConflictError):
    """The learner has not met the requirements of any certificate tier yet."""

    code = "course_certificate_not_eligible"
    message_key = "course-cert-not-eligible"
