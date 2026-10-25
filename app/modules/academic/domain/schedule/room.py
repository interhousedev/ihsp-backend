"""Rooms created from timetable entries and lessons (ROOM-1)."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.schedule.errors import RoomNameInvalidError
from app.shared.text import slugify

RoomStatus = Literal["active", "archived"]
FALLBACK_SLUG = "room"


@dataclass(slots=True)
class Room:
    """A classroom with a public page protected by a PIN."""

    id: UUID
    slug: str
    name: str
    pin: str
    pin_changed_at: dt.datetime
    status: RoomStatus = "active"
    merged_into_id: UUID | None = None


def clean_room_name(raw: str) -> str:
    """Strip a typed room name; an empty name is invalid."""
    name = raw.strip()
    if not name:
        raise RoomNameInvalidError()
    return name


def room_slug(name: str) -> str:
    """Return the address part for a room name: "Кластер" -> "klaster"."""
    return slugify(name) or FALLBACK_SLUG
