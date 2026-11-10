"""Request and response bodies of the face routes."""

from datetime import date, datetime
from uuid import UUID

from app.modules.faces.application.views import (
    CallView,
    CreatedDevice,
    FaceView,
    IdentifyResult,
)
from app.modules.faces.domain.models import Device

from pydantic import BaseModel, Field


class FaceOut(BaseModel):
    """Whether a face is on file."""

    has_face: bool
    locked: bool = Field(description="Set by staff: the student cannot change it.")
    updated_at: datetime | None
    photo_url: str | None

    @classmethod
    def of(cls, view: FaceView) -> "FaceOut":
        """Map the view."""
        return cls(
            has_face=view.has_face,
            locked=view.locked,
            updated_at=view.updated_at,
            photo_url=view.photo_url,
        )


class FacePhotoOut(BaseModel):
    """A user's face photo for administrators."""

    photo_url: str = Field(description="Link to the photo, valid for five minutes.")
    updated_at: datetime | None

    @classmethod
    def of(cls, view: FaceView) -> "FacePhotoOut":
        """Map the view; the caller guarantees a link."""
        return cls(photo_url=view.photo_url or "", updated_at=view.updated_at)


class DeviceOut(BaseModel):
    """An entrance device (never its token)."""

    id: UUID
    name: str
    key_prefix: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None

    @classmethod
    def of(cls, device: Device) -> "DeviceOut":
        """Map the device."""
        return cls(
            id=device.id,
            name=device.name,
            key_prefix=device.key_prefix,
            created_at=device.created_at,
            revoked_at=device.revoked_at,
            last_used_at=device.last_used_at,
        )


class DeviceListOut(BaseModel):
    """All devices."""

    items: list[DeviceOut]


class DeviceCreateIn(BaseModel):
    """A new device."""

    name: str = Field(min_length=1, max_length=200)


class DeviceCreatedOut(BaseModel):
    """A new device; `token` is shown only in this response."""

    id: UUID
    name: str
    key_prefix: str
    created_at: datetime
    token: str

    @classmethod
    def of(cls, created: CreatedDevice) -> "DeviceCreatedOut":
        """Map the created device."""
        return cls(
            id=created.id,
            name=created.name,
            key_prefix=created.key_prefix,
            created_at=created.created_at,
            token=created.token,
        )


class DeviceCallOut(BaseModel):
    """One request of a device."""

    id: UUID
    at: datetime
    status: str
    matched_user_id: UUID | None
    matched_name: str | None
    excused: bool

    @classmethod
    def of(cls, call: CallView) -> "DeviceCallOut":
        """Map the call."""
        return cls(
            id=call.id,
            at=call.at,
            status=call.status,
            matched_user_id=call.matched_user_id,
            matched_name=call.matched_name,
            excused=call.excused,
        )


class DeviceCallListOut(BaseModel):
    """The last 7 days of a device."""

    items: list[DeviceCallOut]


class IdentifiedStudentOut(BaseModel):
    """The student the entrance recognised."""

    id: UUID
    full_name: str
    group: str


class IdentifyOut(BaseModel):
    """The answer to the entrance device."""

    student: IdentifiedStudentOut | None
    excused: bool
    excuse_until: date | None

    @classmethod
    def of(cls, result: IdentifyResult) -> "IdentifyOut":
        """Map the result."""
        student = result.student
        return cls(
            student=(
                IdentifiedStudentOut(
                    id=student.id, full_name=student.full_name, group=student.group
                )
                if student
                else None
            ),
            excused=result.excused,
            excuse_until=(
                date.fromisoformat(result.excuse_until) if result.excuse_until else None
            ),
        )
