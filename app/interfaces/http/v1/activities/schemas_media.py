"""Schemas of club albums, media items, reports and limits."""

import datetime as dt
from typing import Literal
from uuid import UUID

from app.modules.activities.application.media import (
    AlbumView,
    MediaUsageView,
    MediaView,
    UploadStarted,
)
from app.modules.activities.domain.media import (
    AlbumVisibility,
    MediaBlock,
    MediaReport,
)

from pydantic import BaseModel, Field

MAX_BATCH = 100


class MediaOut(BaseModel):
    """A photo or video with signed relative URLs (null while not served)."""

    id: UUID
    club_id: UUID
    kind: str
    status: str
    usage: str
    album_id: UUID | None
    event_id: UUID | None
    announcement_id: UUID | None
    uploaded_by: UUID | None
    caption: str | None
    position: int
    width: int | None
    height: int | None
    duration_ms: int | None
    byte_size: int
    hidden_source: str | None
    created_at: dt.datetime | None
    thumb_url: str | None
    preview_url: str | None
    poster_url: str | None
    video_url: str | None
    original_url: str | None
    can_delete: bool
    can_moderate: bool

    @classmethod
    def of(cls, v: MediaView) -> "MediaOut":
        """From the service view."""
        m = v.media
        return cls(
            id=m.id,
            club_id=m.club_id,
            kind=str(m.kind),
            status=str(m.status),
            usage=str(m.usage),
            album_id=m.album_id,
            event_id=m.event_id,
            announcement_id=m.announcement_id,
            uploaded_by=m.uploaded_by,
            caption=m.caption,
            position=m.position,
            width=m.width,
            height=m.height,
            duration_ms=m.duration_ms,
            byte_size=m.byte_size,
            hidden_source=str(m.hidden_source) if m.hidden_source else None,
            created_at=m.created_at,
            thumb_url=v.thumb_url,
            preview_url=v.preview_url,
            poster_url=v.poster_url,
            video_url=v.video_url,
            original_url=v.original_url,
            can_delete=v.can_delete,
            can_moderate=v.can_moderate,
        )


class AlbumOut(BaseModel):
    """An album with counters and the caller's rights."""

    id: UUID
    club_id: UUID
    title: str
    description: str | None
    visibility: str
    allow_download: bool
    member_uploads: bool
    event_id: UUID | None
    parent_id: UUID | None
    event_date: dt.date | None
    cover_media_id: UUID | None
    created_at: dt.datetime | None
    item_count: int
    folder_count: int
    can_upload: bool
    can_moderate: bool

    @classmethod
    def of(cls, v: AlbumView) -> "AlbumOut":
        """From the service view."""
        a = v.album
        return cls(
            id=a.id,
            club_id=a.club_id,
            title=a.title,
            description=a.description,
            visibility=str(a.visibility),
            allow_download=a.allow_download,
            member_uploads=a.member_uploads,
            event_id=a.event_id,
            parent_id=a.parent_id,
            event_date=a.event_date,
            cover_media_id=a.cover_media_id,
            created_at=a.created_at,
            item_count=v.item_count,
            folder_count=v.folder_count,
            can_upload=v.can_upload,
            can_moderate=v.can_moderate,
        )


class AlbumListOut(BaseModel):
    """Albums under one parent."""

    items: list[AlbumOut]


class AlbumIn(BaseModel):
    """A new album (an event album when `event_id` is given)."""

    title: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = None
    event_id: UUID | None = None
    visibility: AlbumVisibility = AlbumVisibility.SCHOOL
    allow_download: bool = True
    member_uploads: bool = False
    description: str | None = Field(default=None, max_length=4000)
    event_date: dt.date | None = None


class AlbumPatch(BaseModel):
    """Album fields; only the sent ones change."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    visibility: AlbumVisibility | None = None
    allow_download: bool | None = None
    member_uploads: bool | None = None
    event_date: dt.date | None = None
    cover_media_id: UUID | None = None


class UploadIn(BaseModel):
    """Reserve an upload; the browser then PUTs the bytes to `upload.url`."""

    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=1)
    content_type: str = Field(min_length=1, max_length=100)
    sha256_b64: str = Field(min_length=44, max_length=44)
    consent_attested: bool
    album_id: UUID | None = None
    caption: str | None = Field(default=None, max_length=1000)


class UploadTargetOut(BaseModel):
    """Where and how to PUT the bytes."""

    url: str
    method: str
    headers: dict[str, str]


class UploadOut(BaseModel):
    """The reserved item and its upload target."""

    media: MediaOut
    upload: UploadTargetOut


def upload_out(started: UploadStarted, view: MediaView) -> UploadOut:
    """Envelope of a reserved upload."""
    return UploadOut(
        media=MediaOut.of(view),
        upload=UploadTargetOut(
            url=started.upload_url,
            method=started.upload_method,
            headers=started.upload_headers,
        ),
    )


class MediaPageOut(BaseModel):
    """A page of album items."""

    items: list[MediaOut]
    next_cursor: str | None


class MediaPatch(BaseModel):
    """Caption, album or the uploader's own hide switch."""

    caption: str | None = Field(default=None, max_length=1000)
    album_id: UUID | None = None
    hidden: bool | None = None


class BatchIn(BaseModel):
    """Move or delete up to 100 items of one club."""

    ids: list[UUID] = Field(min_length=1, max_length=MAX_BATCH)
    action: Literal["move", "delete"]
    album_id: UUID | None = None


class MediaListOut(BaseModel):
    """Items."""

    items: list[MediaOut]


class ReportIn(BaseModel):
    """Report an item; `is_subject` ("I am in this photo") hides it at once."""

    reason: str = Field(default="", max_length=500)
    is_subject: bool = False


class UsageOut(BaseModel):
    """Storage use and limits of a club; overrides are null when not set."""

    used_bytes: int
    quota_bytes: int
    item_count: int
    photo_max_bytes: int
    video_max_bytes: int
    override_photo_max_bytes: int | None
    override_video_max_bytes: int | None
    override_quota_bytes: int | None

    @classmethod
    def of(cls, u: MediaUsageView) -> "UsageOut":
        """From the service view."""
        return cls(
            used_bytes=u.used_bytes,
            quota_bytes=u.quota_bytes,
            item_count=u.item_count,
            photo_max_bytes=u.photo_max_bytes,
            video_max_bytes=u.video_max_bytes,
            override_photo_max_bytes=u.overrides.photo_max_bytes,
            override_video_max_bytes=u.overrides.video_max_bytes,
            override_quota_bytes=u.overrides.quota_bytes,
        )


class ReportOut(BaseModel):
    """A report of an item."""

    id: UUID
    media_id: UUID
    reporter_id: UUID
    is_subject: bool
    reason: str
    status: str
    created_at: dt.datetime

    @classmethod
    def of(cls, r: MediaReport) -> "ReportOut":
        """From the domain."""
        return cls(
            id=r.id,
            media_id=r.media_id,
            reporter_id=r.reporter_id,
            is_subject=r.is_subject,
            reason=r.reason,
            status=str(r.status),
            created_at=r.created_at,
        )


class BlockOut(BaseModel):
    """A user barred from uploading (club_id null = every club)."""

    id: UUID
    user_id: UUID
    club_id: UUID | None
    reason: str
    created_by: UUID | None
    created_at: dt.datetime

    @classmethod
    def of(cls, b: MediaBlock) -> "BlockOut":
        """From the domain."""
        return cls(
            id=b.id,
            user_id=b.user_id,
            club_id=b.club_id,
            reason=b.reason,
            created_by=b.created_by,
            created_at=b.created_at,
        )
