"""File lifecycle states and reject reasons."""

from enum import StrEnum


class FileStatus(StrEnum):
    """Lifecycle of a stored file (spec -> Models -> File)."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    REJECTED = "rejected"
    DELETED = "deleted"


class RejectReason(StrEnum):
    """Why an upload was rejected after the bytes arrived.

    The values are error ``type`` strings, so the web maps them through ``errors.*``.
    """

    TYPE_MISMATCH = "files/type-mismatch"
    CHECKSUM_MISMATCH = "files/checksum-mismatch"  # wrong size or wrong SHA-256
    PROCESSING_FAILED = "files/processing-failed"
