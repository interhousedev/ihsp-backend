"""Read models of the faces module."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class FaceView:
    """Whether a user has a face on file."""

    has_face: bool
    locked: bool
    updated_at: datetime | None
    photo_url: str | None


@dataclass(frozen=True, slots=True)
class CreatedDevice:
    """A new device with its token, which is shown only now."""

    id: UUID
    name: str
    key_prefix: str
    created_at: datetime
    token: str


@dataclass(frozen=True, slots=True)
class CallView:
    """A device call with the matched student's name."""

    id: UUID
    at: datetime
    status: str
    matched_user_id: UUID | None
    matched_name: str | None
    excused: bool


@dataclass(frozen=True, slots=True)
class IdentifiedStudent:
    """The student a device recognised."""

    id: UUID
    full_name: str
    group: str


@dataclass(frozen=True, slots=True)
class IdentifyResult:
    """The answer to a device: who is at the door and whether they are excused."""

    student: IdentifiedStudent | None
    excused: bool
    excuse_until: str | None
