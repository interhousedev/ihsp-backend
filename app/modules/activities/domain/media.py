"""Club media: albums, photos and videos, reports, limits and signed URLs.

Rules (release 1.17): media is never public; an album is visible to the whole school
(any signed-in user) by default or to the club's people only; ordinary members may
upload when the album allows it and their items are visible at once (post-moderation);
a report "I am in this photo" hides the item instantly; hidden and deleted items are
never served.
"""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from app.modules.activities.domain.errors import (
    BadRequest,
    Conflict,
    Denied,
    Invalid,
)
from app.shared.base_error import BaseError, RateLimitedError

__all__ = [
    "ALBUM_MAX_DEPTH",
    "Album",
    "AlbumDepthError",
    "AlbumExistsError",
    "AlbumVisibility",
    "ClubMediaOverrides",
    "HiddenSource",
    "InvalidMediaUrlError",
    "Media",
    "MediaAlreadyReportedError",
    "MediaBlock",
    "MediaConsentRequiredError",
    "MediaDuplicateError",
    "MediaKind",
    "MediaKindError",
    "MediaLimits",
    "MediaNotReadyError",
    "MediaQuotaExceededError",
    "MediaRateLimitedError",
    "MediaReport",
    "MediaStateError",
    "MediaStatus",
    "MediaTooLargeError",
    "MediaTypeNotAllowedError",
    "MediaUploadBlockedError",
    "MediaUploadMismatchError",
    "MediaUsage",
    "MediaVariant",
    "ReportStatus",
    "Viewer",
    "can_delete_media",
    "can_upload_to_album",
    "can_view_album",
    "check_album_depth",
    "check_quota",
    "check_size",
    "kind_for_content_type",
    "kind_for_name",
    "resolve_limits",
    "sign_media_url",
    "url_path",
    "validate_logo_file",
    "verify_media_url",
]

ALBUM_MAX_DEPTH = 3  # an album with no parent has depth 1
URL_PREFIX = "media."
MAX_REPORT_REASON = 500


class MediaStateError(Conflict):
    """The media state does not allow this."""


class MediaNotReadyError(Conflict):
    """The media is not processed yet (or failed)."""


class MediaQuotaExceededError(Conflict):
    """The club's media quota is used up."""


class MediaDuplicateError(Conflict):
    """The same content is already in this album."""


class MediaUploadMismatchError(Conflict):
    """The uploaded object differs from what was declared."""


class MediaAlreadyReportedError(Conflict):
    """The user has already reported this item."""


class AlbumExistsError(Conflict):
    """The event already has a root album."""


class AlbumDepthError(Invalid):
    """Folders may nest at most ``ALBUM_MAX_DEPTH`` levels."""


class MediaConsentRequiredError(Invalid):
    """The uploader did not confirm the attestation."""


class MediaKindError(Invalid):
    """The media kind does not fit here (e.g. a video as an event cover)."""


class MediaUploadBlockedError(Denied):
    """The user is barred from uploading club media."""


class MediaTooLargeError(BaseError):
    """The file is larger than the limit (413)."""

    code = "activities/media-too-large"
    message_key = "activities-media-too-large"
    status = 413


class MediaTypeNotAllowedError(BaseError):
    """The file type is not a photo or video format we take (415)."""

    code = "activities/media-type-not-allowed"
    message_key = "activities-media-type-not-allowed"
    status = 415


class MediaRateLimitedError(RateLimitedError):
    """Too many uploads in an hour."""

    code = "activities/media-rate-limited"
    message_key = "activities-media-rate-limited"


class InvalidMediaUrlError(BadRequest):
    """The signed URL is tampered, expired or for another item (answer 404)."""


class MediaKind(StrEnum):
    """Photo or video."""

    PHOTO = "photo"
    VIDEO = "video"


class MediaUsage(StrEnum):
    """Where a media item is used."""

    STAGED = "staged"  # uploaded, not attached yet
    ALBUM = "album"
    EVENT_COVER = "event_cover"
    ANNOUNCEMENT = "announcement"


class MediaStatus(StrEnum):
    """Lifecycle of a media item."""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    HIDDEN = "hidden"
    DELETED = "deleted"


class HiddenSource(StrEnum):
    """Who hid an item (decides who may restore it)."""

    MODERATOR = "moderator"
    UPLOADER = "uploader"
    REPORT = "report"  # an "I am in this photo" report, hidden at once


class AlbumVisibility(StrEnum):
    """Who sees an album."""

    MEMBERS = "members"  # active members, organizers, event attendees, staff
    SCHOOL = "school"  # any signed-in user (default)


class ReportStatus(StrEnum):
    """Outcome of a media report."""

    OPEN = "open"
    UPHELD = "upheld"
    DISMISSED = "dismissed"


class MediaVariant(StrEnum):
    """What a signed URL serves."""

    THUMB = "thumb"
    PREVIEW = "preview"
    POSTER = "poster"
    VIDEO = "video"
    ORIGINAL = "original"


_PHOTO_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_VIDEO_TYPES = frozenset({"video/mp4", "video/webm", "video/quicktime"})
_PHOTO_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_VIDEO_EXT = frozenset({".mp4", ".webm", ".mov"})


def kind_for_content_type(content_type: str) -> MediaKind:
    """Photo or video by the declared type; anything else is refused (415)."""
    clean = content_type.split(";", 1)[0].strip().lower()
    if clean in _PHOTO_TYPES:
        return MediaKind.PHOTO
    if clean in _VIDEO_TYPES:
        return MediaKind.VIDEO
    raise MediaTypeNotAllowedError(params={"content_type": clean})


def kind_for_name(name: str) -> MediaKind:
    """Photo or video by the file extension; anything else is refused (415)."""
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in _PHOTO_EXT:
        return MediaKind.PHOTO
    if ext in _VIDEO_EXT:
        return MediaKind.VIDEO
    raise MediaTypeNotAllowedError(params={"extension": ext})


@dataclass(frozen=True, slots=True)
class ClubMediaOverrides:
    """Per-club limits set by administrators; ``None`` = the settings default."""

    photo_max_bytes: int | None = None
    video_max_bytes: int | None = None
    quota_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class MediaLimits:
    """The limits in force for one club."""

    photo_max_bytes: int
    video_max_bytes: int
    quota_bytes: int
    announcement_photos_max: int = 10
    album_items_max: int = 500

    def max_bytes(self, kind: MediaKind) -> int:
        """Largest single file of the kind."""
        return self.photo_max_bytes if kind == MediaKind.PHOTO else self.video_max_bytes


def resolve_limits(
    overrides: ClubMediaOverrides,
    *,
    photo_max_bytes: int,
    video_max_bytes: int,
    quota_bytes: int,
    announcement_photos_max: int = 10,
    album_items_max: int = 500,
) -> MediaLimits:
    """Club overrides win over the settings defaults (each limit on its own)."""
    return MediaLimits(
        photo_max_bytes=_pick(overrides.photo_max_bytes, photo_max_bytes),
        video_max_bytes=_pick(overrides.video_max_bytes, video_max_bytes),
        quota_bytes=_pick(overrides.quota_bytes, quota_bytes),
        announcement_photos_max=announcement_photos_max,
        album_items_max=album_items_max,
    )


def _pick(override: int | None, default: int) -> int:
    return default if override is None else override


def check_size(kind: MediaKind, size: int, limits: MediaLimits) -> None:
    """Reject empty and too big files (413)."""
    if size < 1:
        raise MediaTypeNotAllowedError(params={"size": size})
    top = limits.max_bytes(kind)
    if size > top:
        raise MediaTooLargeError(
            params={"size": size, "max_bytes": top, "kind": kind.value}
        )


def check_quota(used_bytes: int, size: int, limits: MediaLimits) -> None:
    """Reject an upload that would push the club over its quota (409)."""
    if used_bytes + size > limits.quota_bytes:
        raise MediaQuotaExceededError(
            params={
                "used_bytes": used_bytes,
                "quota_bytes": limits.quota_bytes,
                "size": size,
            }
        )


def check_album_depth(parent_depth: int) -> int:
    """Depth of a new album under a parent of ``parent_depth`` (0 = no parent)."""
    depth = parent_depth + 1
    if depth > ALBUM_MAX_DEPTH:
        raise AlbumDepthError(params={"max_depth": ALBUM_MAX_DEPTH})
    return depth


@dataclass(slots=True)
class Album:
    """A folder of media: a root album of an event, or a free folder of a club."""

    id: UUID
    club_id: UUID
    title: str
    visibility: AlbumVisibility = AlbumVisibility.SCHOOL
    allow_download: bool = True
    member_uploads: bool = False
    event_id: UUID | None = None
    parent_id: UUID | None = None
    description: str | None = None
    event_date: date | None = None
    cover_media_id: UUID | None = None
    source_ref: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        """True after a soft delete."""
        return self.deleted_at is not None

    def delete(self, now: datetime) -> None:
        """Mark the album deleted; the application deletes its items too."""
        self.deleted_at = self.deleted_at or now


@dataclass(frozen=True, slots=True)
class Viewer:
    """What the access checks need to know about the person looking."""

    user_id: UUID
    signed_in: bool = True
    is_platform_staff: bool = False
    is_club_person: bool = False  # active member, organizer or team
    attended_event: bool = False  # RSVP'd to the album's event


def can_view_album(album: Album, viewer: Viewer) -> bool:
    """Deleted albums are invisible; ``school`` needs only a sign-in."""
    if album.is_deleted or not viewer.signed_in:
        return False
    if viewer.is_platform_staff or viewer.is_club_person:
        return True
    if album.visibility == AlbumVisibility.SCHOOL:
        return True
    return album.event_id is not None and viewer.attended_event


def can_upload_to_album(
    album: Album, viewer: Viewer, *, has_edit_events: bool, blocked: bool
) -> bool:
    """Organizers always; ordinary members and attendees when the album allows it."""
    if blocked or album.is_deleted:
        return False
    if has_edit_events:
        return True
    return album.member_uploads and (viewer.is_club_person or viewer.attended_event)


def can_delete_media(media: "Media", user_id: UUID, *, can_moderate: bool) -> bool:
    """The uploader deletes an own item; moderators any item of the club."""
    own = media.uploaded_by is not None and media.uploaded_by == user_id
    return can_moderate or own


@dataclass(slots=True)
class Media:
    """A photo or video with its derivatives (files module ids)."""

    id: UUID
    club_id: UUID
    kind: MediaKind
    uploaded_by: UUID | None
    original_file_id: UUID | None = None
    usage: MediaUsage = MediaUsage.STAGED
    status: MediaStatus = MediaStatus.UPLOADING
    album_id: UUID | None = None
    event_id: UUID | None = None
    announcement_id: UUID | None = None
    thumb_file_id: UUID | None = None
    preview_file_id: UUID | None = None
    poster_file_id: UUID | None = None
    byte_size: int = 0
    content_sha256: str = ""
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    caption: str | None = None
    position: int = 0
    consent_attested: bool = False
    imported: bool = False
    source_ref: str | None = None
    hidden_reason: str | None = None
    hidden_by: UUID | None = None
    hidden_source: HiddenSource | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    # --- processing ---------------------------------------------------------
    def mark_processing(self) -> None:
        """The upload is complete and verified; derivatives are being made."""
        if self.status != MediaStatus.UPLOADING:
            raise MediaStateError(params={"status": self.status.value})
        if not self.consent_attested:
            raise MediaConsentRequiredError()
        self.status = MediaStatus.PROCESSING

    def mark_ready(
        self,
        *,
        thumb_file_id: UUID,
        preview_file_id: UUID,
        byte_size: int,
        poster_file_id: UUID | None = None,
        width: int | None = None,
        height: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Derivatives exist; ``byte_size`` is the original plus all derivatives."""
        if self.status != MediaStatus.PROCESSING:
            raise MediaStateError(params={"status": self.status.value})
        self.thumb_file_id = thumb_file_id
        self.preview_file_id = preview_file_id
        self.poster_file_id = poster_file_id
        self.byte_size = byte_size
        self.width = width
        self.height = height
        self.duration_ms = duration_ms
        self.status = MediaStatus.READY

    def mark_failed(self) -> None:
        """Processing failed (corrupt file, bomb, spoofed type)."""
        if self.status not in (MediaStatus.UPLOADING, MediaStatus.PROCESSING):
            raise MediaStateError(params={"status": self.status.value})
        self.status = MediaStatus.FAILED

    # --- placement ----------------------------------------------------------
    def attach_to_album(self, album_id: UUID, position: int) -> None:
        """Put a staged or album item in an album."""
        self._require_usage(MediaUsage.STAGED, MediaUsage.ALBUM)
        self._clear_targets()
        self.usage, self.album_id, self.position = MediaUsage.ALBUM, album_id, position

    def attach_to_announcement(self, announcement_id: UUID, position: int) -> None:
        """Use a ready, staged photo in an announcement."""
        self._require_usage(MediaUsage.STAGED)
        self._require_ready_photo()
        self._clear_targets()
        self.usage = MediaUsage.ANNOUNCEMENT
        self.announcement_id, self.position = announcement_id, position

    def attach_as_cover(self, event_id: UUID) -> None:
        """Use a ready photo as an event cover (staged, or already this cover)."""
        if self.usage == MediaUsage.EVENT_COVER and self.event_id == event_id:
            return
        self._require_usage(MediaUsage.STAGED)
        self._require_ready_photo()
        self._clear_targets()
        self.usage, self.event_id = MediaUsage.EVENT_COVER, event_id

    def _require_usage(self, *allowed: MediaUsage) -> None:
        if self.is_gone or self.usage not in allowed:
            raise MediaStateError(params={"usage": self.usage.value})

    def _require_ready_photo(self) -> None:
        if self.kind != MediaKind.PHOTO:
            raise MediaKindError(params={"kind": self.kind.value})
        if self.status != MediaStatus.READY:
            raise MediaNotReadyError(params={"status": self.status.value})

    def _clear_targets(self) -> None:
        self.album_id = self.event_id = self.announcement_id = None

    # --- visibility ---------------------------------------------------------
    @property
    def is_gone(self) -> bool:
        """Soft-deleted."""
        return self.status == MediaStatus.DELETED

    @property
    def is_served(self) -> bool:
        """Only ready items are served; hidden and deleted ones never are."""
        return self.status == MediaStatus.READY

    def hide(
        self, *, by: UUID | None, reason: str | None, source: HiddenSource
    ) -> None:
        """Take a ready item off display at once (reversible)."""
        if self.status == MediaStatus.HIDDEN:
            return
        if self.status != MediaStatus.READY:
            raise MediaStateError(params={"status": self.status.value})
        self.status = MediaStatus.HIDDEN
        self.hidden_by, self.hidden_reason, self.hidden_source = by, reason, source

    def restore(self, *, by_moderator: bool, by: UUID | None = None) -> None:
        """Show a hidden item again.

        The uploader may undo only an own hide; an item hidden by a moderator or by
        a report waits for a moderator.
        """
        if self.status != MediaStatus.HIDDEN:
            raise MediaStateError(params={"status": self.status.value})
        own = self.hidden_source == HiddenSource.UPLOADER and by == self.uploaded_by
        if not by_moderator and not own:
            raise MediaStateError(params={"hidden_source": str(self.hidden_source)})
        self.status = MediaStatus.READY
        self.hidden_by = self.hidden_reason = self.hidden_source = None

    def soft_delete(self, now: datetime) -> None:
        """Hide for good-after-grace: the purge job removes the files later."""
        if self.status == MediaStatus.DELETED:
            return
        self.status = MediaStatus.DELETED
        self.deleted_at = now

    def undelete(self) -> None:
        """Undo a soft delete inside the undo window (back to ready)."""
        if self.status != MediaStatus.DELETED:
            raise MediaStateError(params={"status": self.status.value})
        self.status = MediaStatus.READY
        self.deleted_at = None

    def purge_due(self, now: datetime, after_days: int) -> bool:
        """True once a soft-deleted item is past its undo window."""
        return self.deleted_at is not None and now >= self.deleted_at + timedelta(
            days=after_days
        )

    def staged_expired(self, now: datetime, ttl_hours: int) -> bool:
        """True for an upload never attached within the TTL."""
        return (
            self.usage == MediaUsage.STAGED
            and self.created_at is not None
            and not self.is_gone
            and now >= self.created_at + timedelta(hours=ttl_hours)
        )

    # --- reports ------------------------------------------------------------
    def report(
        self,
        reporter_id: UUID,
        *,
        is_subject: bool,
        reason: str,
        existing_reporters: frozenset[UUID],
        report_id: UUID,
        now: datetime,
    ) -> "MediaReport":
        """Record a report; "I am in this photo" hides the item at once."""
        if reporter_id in existing_reporters:
            raise MediaAlreadyReportedError()
        if self.status not in (MediaStatus.READY, MediaStatus.HIDDEN):
            raise MediaStateError(params={"status": self.status.value})
        text = reason.strip()[:MAX_REPORT_REASON]
        if is_subject and self.status == MediaStatus.READY:
            self.hide(by=reporter_id, reason=text or None, source=HiddenSource.REPORT)
        return MediaReport(
            id=report_id,
            media_id=self.id,
            reporter_id=reporter_id,
            is_subject=is_subject,
            reason=text,
            created_at=now,
        )


@dataclass(slots=True)
class MediaReport:
    """A viewer's report of a media item."""

    id: UUID
    media_id: UUID
    reporter_id: UUID
    is_subject: bool
    reason: str
    created_at: datetime
    status: ReportStatus = ReportStatus.OPEN
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None

    def resolve(self, upheld: bool, by: UUID, now: datetime) -> None:
        """A moderator closes the report once."""
        if self.status != ReportStatus.OPEN:
            raise MediaStateError(params={"status": self.status.value})
        self.status = ReportStatus.UPHELD if upheld else ReportStatus.DISMISSED
        self.resolved_by, self.resolved_at = by, now


@dataclass(frozen=True, slots=True)
class MediaBlock:
    """A user barred from uploading club media (``club_id`` None = every club)."""

    id: UUID
    user_id: UUID
    club_id: UUID | None
    reason: str
    created_by: UUID | None
    created_at: datetime


# --- signed URLs --------------------------------------------------------------
def _bucket_expiry(now: datetime, bucket_hours: int) -> int:
    """Expiry rounded up to a bucket so the URL is the same all day (cacheable).

    Valid for between one and two buckets.
    """
    step = bucket_hours * 3600
    return (int(now.astimezone(UTC).timestamp()) // step + 2) * step


def _sign(secret: str, media_id: UUID, variant: MediaVariant, exp: int) -> str:
    msg = f"{URL_PREFIX}{media_id}.{variant.value}.{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def sign_media_url(
    secret: str,
    media_id: UUID,
    variant: MediaVariant,
    now: datetime,
    *,
    bucket_hours: int = 24,
) -> tuple[int, str]:
    """Return ``(exp, signature)`` for ``/media/{id}/{variant}?e=&s=``."""
    exp = _bucket_expiry(now, bucket_hours)
    return exp, _sign(secret, media_id, variant, exp)


def verify_media_url(
    secret: str,
    media_id: UUID,
    variant: MediaVariant,
    exp: int,
    signature: str,
    now: datetime,
) -> None:
    """Raise ``InvalidMediaUrlError`` for a tampered or expired URL."""
    good = hmac.compare_digest(signature, _sign(secret, media_id, variant, exp))
    if not good or now.astimezone(UTC).timestamp() > exp:
        raise InvalidMediaUrlError()


def url_path(media_id: UUID, variant: MediaVariant, exp: int, signature: str) -> str:
    """The relative signed URL."""
    return f"/v1/activities/media/{media_id}/{variant.value}?e={exp}&s={signature}"


LOGO_MAX_BYTES = 5 * 1024 * 1024
_LOGO_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


def validate_logo_file(
    *,
    actor_id: UUID,
    owner_id: UUID,
    content_type: str,
    byte_size: int,
    club_id: UUID,
    current_logo_id: UUID | None,
    file_id: UUID,
) -> None:
    """A club logo must be the actor's own small image, or already the club's logo.

    Closes the hole where any file id could be set as a logo (and then served).
    """
    if file_id == current_logo_id:
        return
    if owner_id not in (actor_id, club_id):
        raise Denied()
    if content_type.lower() not in _LOGO_TYPES:
        raise MediaTypeNotAllowedError(params={"content_type": content_type})
    if byte_size > LOGO_MAX_BYTES:
        raise MediaTooLargeError(
            params={"size": byte_size, "max_bytes": LOGO_MAX_BYTES}
        )
