"""Request bodies of /v1/lessons/{lesson_id}/resources."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AddResourceBody(BaseModel):
    """Attach a URL or a file to a lesson."""

    role: Literal["material", "attachment"]
    kind: Literal["url", "file"]
    target_url: str | None = Field(default=None, max_length=2048)
    file_id: UUID | None = None
    also_lesson_ids: list[UUID] = Field(default_factory=list, max_length=20)


class HideResourceBody(BaseModel):
    """Hide or show a resource."""

    hidden: bool
