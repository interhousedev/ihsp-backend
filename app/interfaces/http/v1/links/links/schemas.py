"""Request bodies of /v1/links."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.links.schemas import LinkItem

from pydantic import BaseModel, Field


class CreateLinkBody(BaseModel):
    """Create a short link to a URL or to one of the caller's files."""

    kind: Literal["url", "file"]
    target_url: str | None = Field(default=None, max_length=2048)
    file_id: UUID | None = None


class LinkPageResponse(BaseModel):
    """Page<LinkItem>."""

    items: list[LinkItem]
    next_cursor: str | None
