"""Schemas of the room routes."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admin_schedule.shared_schemas import ApiModel

from pydantic import BaseModel, Field


class RoomRenameBody(BaseModel):
    """Body of PATCH /v1/admin/rooms/{id}."""

    name: str = Field(min_length=1, max_length=255)


class RoomMergeBody(BaseModel):
    """Body of POST /v1/admin/rooms/{id}/merge."""

    into_room_id: UUID


class RoomResponse(ApiModel):
    """Room."""

    id: UUID
    slug: str
    name: str
    pin: str
    url: str
    status: Literal["active", "archived"]
    lessons_this_week: int
