"""Request and response models of sharing a file (FILE-SHARE)."""

from datetime import datetime
from uuid import UUID

from app.modules.files.domain.sharing import FileShareVia

from pydantic import BaseModel, Field


class JoinFileShareBody(BaseModel):
    """The token of a share link, in the body so that it stays out of access logs."""

    token: str = Field(min_length=1, max_length=128)


class FileShareLinkResponse(BaseModel):
    """A new token: it is shown this once, only its hash is stored."""

    token: str


class FileSharePersonResponse(BaseModel):
    """A person with access."""

    user_id: UUID
    name: str
    via: FileShareVia
    created_at: datetime


class FileSharesResponse(BaseModel):
    """Who has access and whether a link works."""

    link_active: bool
    people: list[FileSharePersonResponse]


class SharedFileItem(BaseModel):
    """A file shared with the caller: no storage key, usage list or owner id."""

    id: UUID
    name: str
    content_type: str
    byte_size: int
    created_at: datetime
    owner_name: str


class SharedFilesResponse(BaseModel):
    """`{items}` of the files shared with the caller."""

    items: list[SharedFileItem]
