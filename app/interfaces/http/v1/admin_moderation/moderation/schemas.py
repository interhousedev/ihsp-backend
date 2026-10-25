"""JSON shapes of the moderation endpoints."""

from app.interfaces.http.v1.links.schemas import ModerationItem

from pydantic import BaseModel, Field


class ModerationPageResponse(BaseModel):
    """Page<ModerationItem>."""

    items: list[ModerationItem]
    next_cursor: str | None


class DisableBody(BaseModel):
    """Why a link is disabled."""

    reason: str = Field(min_length=1, max_length=500)
