"""The file entity: metadata of one object in storage."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.files.domain.status import FileStatus, RejectReason
from app.shared.contracts.files import FilePurpose, FileRef, FileScope

TEXT_SUFFIX = ".txt"


@dataclass(slots=True)
class StoredFile:
    """Metadata of a file; the bytes live in S3 under ``key``."""

    id: UUID
    owner_id: UUID
    scope: FileScope
    purpose: FilePurpose
    key: str
    name: str
    content_type: str
    byte_size: int
    checksum: str
    status: FileStatus
    created_at: datetime
    updated_at: datetime
    reject_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    text_bytes: int | None = None
    term_id: UUID | None = None
    expires_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def text_key(self) -> str:
        """Key of the extracted-text sidecar object."""
        return self.key + TEXT_SUFFIX

    def storage_keys(self) -> list[str]:
        """Every object of this file: the content and the text sidecar."""
        return [self.key, self.text_key]

    def is_owned_by(self, user_id: UUID) -> bool:
        """Return True if the user owns the file."""
        return self.owner_id == user_id

    def to_ref(self) -> FileRef:
        """Return the cross-module view of the file."""
        return FileRef(
            id=self.id,
            owner_id=self.owner_id,
            scope=self.scope,
            purpose=self.purpose,
            name=self.name,
            content_type=self.content_type,
            byte_size=self.byte_size,
            status=self.status.value,
            text_bytes=self.text_bytes,
        )

    def mark_processing(self, content_type: str, now: datetime) -> None:
        """Accept the uploaded object and queue it for processing."""
        self.status = FileStatus.PROCESSING
        self.content_type = content_type
        self.updated_at = now

    def reject(self, reason: RejectReason, now: datetime) -> None:
        """Refuse the upload; the object must be deleted by the caller."""
        self.status = FileStatus.REJECTED
        self.reject_reason = reason.value
        self.text_bytes = None
        self.updated_at = now

    def mark_ready(
        self, now: datetime, *, text_bytes: int | None, metadata: dict[str, Any]
    ) -> None:
        """Finish processing; ``text_bytes`` is None when there is no text."""
        self.status = FileStatus.READY
        self.text_bytes = text_bytes
        self.metadata = {**self.metadata, **metadata}
        self.updated_at = now

    def mark_deleted(self, now: datetime) -> None:
        """Soft-delete the row; objects are deleted by the caller."""
        self.status = FileStatus.DELETED
        self.deleted_at = now
        self.text_bytes = None
        self.updated_at = now

    def rename(self, name: str, now: datetime) -> None:
        """Change the display name (the key never changes)."""
        self.name = name
        self.updated_at = now
