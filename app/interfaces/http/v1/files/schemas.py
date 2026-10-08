"""Request and response models of the files endpoints (API contract -> Files)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.modules.files.domain.status import FileStatus
from app.shared.contracts.files import FilePurpose

from pydantic import BaseModel, Field


class UsedByItem(BaseModel):
    """A place that uses a file."""

    kind: Literal["link", "lesson", "chat"]
    id: UUID
    label: str


class FileItem(BaseModel):
    """Metadata of a file as the web apps see it."""

    id: UUID
    name: str
    content_type: str
    byte_size: int
    purpose: FilePurpose
    status: FileStatus
    reject_reason: str | None
    text_bytes: int | None
    assistant_ready: bool
    created_at: datetime
    expires_on: date | None
    used_by: list[UsedByItem]


class RequestUploadBody(BaseModel):
    """Declared properties of the file the client is going to upload."""

    name: str = Field(min_length=1, max_length=1024)
    size: int
    content_type: str = Field(max_length=255)
    sha256_b64: str = Field(min_length=1, max_length=128)
    purpose: Literal["ai_upload", "link"]


class UploadInfo(BaseModel):
    """The request the client sends to storage."""

    url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]


class UploadResponse(BaseModel):
    """The pending file and how to upload its bytes."""

    file: FileItem
    upload: UploadInfo


class RenameFileBody(BaseModel):
    """New display name."""

    name: str = Field(min_length=1, max_length=1024)


class DownloadUrlResponse(BaseModel):
    """A presigned URL valid for 60 seconds."""

    url: str
    expires_at: datetime


class DeleteFileResponse(BaseModel):
    """What used the file before it was deleted."""

    used_by: list[UsedByItem]


class StorageResponse(BaseModel):
    """Quota bar data."""

    used_bytes: int
    quota_bytes: int
    term_id: UUID | None
    expires_on: date | None
