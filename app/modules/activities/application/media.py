"""Club media: albums, uploads, post-moderation, quota, reports, purge."""

import base64
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

from app.modules.activities.application.common import (
    active_member,
    load_club,
    load_event,
    permissions,
)
from app.modules.activities.domain.access import (
    Permission,
    PermissionDeniedError,
    global_permissions,
    is_platform_staff,
)
from app.modules.activities.domain.club import (
    Club,
    ClubInvalidError,
    ClubStateError,
    ClubStatus,
)
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.media import (
    Album,
    AlbumExistsError,
    AlbumVisibility,
    ClubMediaOverrides,
    HiddenSource,
    InvalidMediaUrlError,
    Media,
    MediaBlock,
    MediaConsentRequiredError,
    MediaDuplicateError,
    MediaKind,
    MediaKindError,
    MediaLimits,
    MediaQuotaExceededError,
    MediaRateLimitedError,
    MediaReport,
    MediaStateError,
    MediaStatus,
    MediaTooLargeError,
    MediaTypeNotAllowedError,
    MediaUploadBlockedError,
    MediaUploadMismatchError,
    MediaUsage,
    MediaVariant,
    Viewer,
    can_delete_media,
    can_upload_to_album,
    can_view_album,
    check_album_depth,
    check_quota,
    check_size,
    kind_for_content_type,
    kind_for_name,
    resolve_limits,
    sign_media_url,
    url_path,
    verify_media_url,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.base_error import RateLimitedError

from uuid_utils.compat import uuid7

ALBUM_PAGE = 60
_STAFF_STATUSES = frozenset(
    {
        MediaStatus.READY,
        MediaStatus.HIDDEN,
        MediaStatus.PROCESSING,
        MediaStatus.FAILED,
    }
)
_PUBLIC_STATUSES = frozenset({MediaStatus.READY})
_STREAMED = frozenset({MediaVariant.THUMB, MediaVariant.PREVIEW, MediaVariant.POSTER})
REDIRECT_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class ServedVariant:
    """What the signed route serves: bytes it streams, or a presigned redirect."""

    file_id: UUID
    redirect: bool
    content_type: str


@dataclass(frozen=True, slots=True)
class UploadStarted:
    """A reserved upload: the new item and where the browser PUTs the bytes."""

    media: Media
    upload_url: str
    upload_method: str
    upload_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class MediaView:
    """An item with signed relative URLs (``None`` while not served)."""

    media: Media
    thumb_url: str | None
    preview_url: str | None
    poster_url: str | None
    video_url: str | None
    original_url: str | None
    can_delete: bool
    can_moderate: bool


@dataclass(frozen=True, slots=True)
class MediaPage:
    """One page of an album; ``next_cursor`` is ``None`` at the end."""

    items: list[MediaView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AlbumView:
    """An album with counters and what the viewer may do."""

    album: Album
    item_count: int
    folder_count: int
    can_upload: bool
    can_moderate: bool


@dataclass(frozen=True, slots=True)
class MediaUsageView:
    """Quota use of a club and the limits in force."""

    used_bytes: int
    quota_bytes: int
    item_count: int
    photo_max_bytes: int
    video_max_bytes: int
    overrides: ClubMediaOverrides


@dataclass(frozen=True, slots=True)
class ReviewPage:
    """Moderation queue page."""

    items: list[MediaView]
    reports: dict[UUID, list[MediaReport]]
    total: int


def _title(value: object) -> str:
    """A plain title from a string or a ``{locale: text}`` mapping."""
    if isinstance(value, dict):
        for key in ("en", "ru", "uz"):
            if value.get(key):
                return str(value[key])
        return str(next(iter(value.values()), ""))
    return str(value or "")


def _sha_hex(sha256_b64: str) -> str:
    try:
        raw = base64.b64decode(sha256_b64, validate=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise ClubInvalidError(params={"field": "sha256_b64"}) from exc
    if len(raw) != 32:
        raise ClubInvalidError(params={"field": "sha256_b64"})
    return raw.hex()


class MediaService:
    """Albums and media of clubs; every check is made here, not in the edges."""

    def __init__(self, deps: Ports) -> None:
        """Keep the ports."""
        self._p = deps

    # ------------------------------------------------------------ access ----

    async def _is_moderator(self, actor: Actor, club_id: UUID) -> bool:
        perms = await permissions(self._p, actor, club_id)
        return Permission.MODERATE_MEDIA in perms

    def _require_global(self, actor: Actor) -> None:
        if Permission.MODERATE_MEDIA not in global_permissions(actor.roles):
            raise PermissionDeniedError()

    async def _viewer(
        self, actor: Actor, club_id: UUID, event_id: UUID | None = None
    ) -> Viewer:
        person = await active_member(self._p, club_id, actor.user_id) is not None
        attended = False
        if event_id is not None:
            rsvp = await self._p.events.get_rsvp(event_id, actor.user_id)
            attended = rsvp is not None and rsvp.checked_in_at is not None
        return Viewer(
            user_id=actor.user_id,
            is_platform_staff=is_platform_staff(actor.roles),
            is_club_person=person,
            attended_event=attended,
        )

    async def _album(self, actor: Actor, album_id: UUID) -> tuple[Album, Viewer]:
        """A live album the actor may see, else 404."""
        album = await self._p.albums.get(album_id)
        if album is None or album.is_deleted:
            raise ActivitiesNotFoundError()
        viewer = await self._viewer(actor, album.club_id, album.event_id)
        if not can_view_album(album, viewer):
            raise ActivitiesNotFoundError()
        return album, viewer

    async def _can_see(  # noqa: C901 - one branch per visibility rule
        self, actor: Actor, media: Media
    ) -> bool:
        if media.status == MediaStatus.DELETED:
            return False
        moderator = await self._is_moderator(actor, media.club_id)
        mine = media.uploaded_by == actor.user_id
        if media.status not in _PUBLIC_STATUSES and not (moderator or mine):
            return False
        if media.usage == MediaUsage.ALBUM and media.album_id is not None:
            album = await self._p.albums.get(media.album_id)
            if album is None or album.is_deleted:
                return False
            viewer = await self._viewer(actor, media.club_id, album.event_id)
            return can_view_album(album, viewer)
        if media.usage == MediaUsage.STAGED:
            return moderator or mine
        club = await self._p.clubs.get(media.club_id)
        if club is None:
            return False
        if media.usage == MediaUsage.EVENT_COVER:
            if club.visibility_public and club.status == ClubStatus.ACTIVE:
                return True
        return moderator or bool(
            await active_member(self._p, media.club_id, actor.user_id)
        )

    async def _media(self, actor: Actor, media_id: UUID) -> Media:
        """An item the actor may see, else 404 (other clubs included)."""
        media = await self._p.media.get(media_id)
        if media is None or not await self._can_see(actor, media):
            raise ActivitiesNotFoundError()
        return media

    async def _limits(self, club_id: UUID) -> MediaLimits:
        c = self._p.media_config
        return resolve_limits(
            await self._p.media.overrides(club_id),
            photo_max_bytes=c.photo_max_bytes,
            video_max_bytes=c.video_max_bytes,
            quota_bytes=c.quota_bytes,
            announcement_photos_max=c.announcement_photos_max,
            album_items_max=c.album_items_max,
        )

    async def _save(self, media: Media) -> None:
        media.updated_at = self._p.clock.now()
        await self._p.media.save(media)

    # ----------------------------------------------------------- views ------

    async def _audience(
        self,
        media: Media,
        albums: dict[UUID, Album | None] | None = None,
        clubs: dict[UUID, Club | None] | None = None,
    ) -> str | None:
        """The live audience an item's URLs are signed for; None when unservable.

        The audience is part of the URL key, so narrowing an album to members,
        deleting it, or making a club private voids the URLs issued before.
        """
        albums = {} if albums is None else albums
        clubs = {} if clubs is None else clubs
        if media.usage == MediaUsage.ALBUM:
            if media.album_id is None:
                return None
            if media.album_id not in albums:
                albums[media.album_id] = await self._p.albums.get(media.album_id)
            album = albums[media.album_id]
            if album is None or album.is_deleted:
                return None
            return f"album:{album.visibility}"
        if media.club_id not in clubs:
            clubs[media.club_id] = await self._p.clubs.get(media.club_id)
        club = clubs[media.club_id]
        if club is None:
            return None
        public = club.visibility_public and club.status == ClubStatus.ACTIVE
        if media.usage == MediaUsage.EVENT_COVER and public:
            return "public"
        return "club"

    def _url_secret(self, audience: str) -> str:
        return f"{self._p.secret}\x1f{audience}"

    def _urls(
        self, media: Media, audience: str | None, *, original: bool
    ) -> dict[str, str | None]:
        out: dict[str, str | None] = dict.fromkeys(
            ("thumb", "preview", "poster", "video", "original")
        )
        if audience is None or not media.is_served:
            return out
        now = self._p.clock.now()
        hours = self._p.media_config.url_bucket_hours
        secret = self._url_secret(audience)

        def sign(variant: MediaVariant) -> str:
            exp, sig = sign_media_url(
                secret, media.id, variant, now, bucket_hours=hours
            )
            return url_path(media.id, variant, exp, sig)

        out["thumb"] = sign(MediaVariant.THUMB)
        if media.kind == MediaKind.PHOTO:
            out["preview"] = sign(MediaVariant.PREVIEW)
        if media.poster_file_id:
            out["poster"] = sign(MediaVariant.POSTER)
        if media.kind == MediaKind.VIDEO:
            out["video"] = sign(MediaVariant.VIDEO)
        if original:
            out["original"] = sign(MediaVariant.ORIGINAL)
        return out

    async def views(self, actor: Actor, items: list[Media]) -> list[MediaView]:
        """Items with signed URLs and per-item rights."""
        moderators: dict[UUID, bool] = {}
        albums: dict[UUID, Album | None] = {}
        clubs: dict[UUID, Club | None] = {}
        out: list[MediaView] = []
        for m in items:
            if m.club_id not in moderators:
                moderators[m.club_id] = await self._is_moderator(actor, m.club_id)
            mod = moderators[m.club_id]
            allow = mod
            if m.album_id is not None:
                if m.album_id not in albums:
                    albums[m.album_id] = await self._p.albums.get(m.album_id)
                album = albums[m.album_id]
                allow = allow or bool(album and album.allow_download)
            audience = await self._audience(m, albums, clubs)
            urls = self._urls(m, audience, original=allow)
            out.append(
                MediaView(
                    media=m,
                    thumb_url=urls["thumb"],
                    preview_url=urls["preview"],
                    poster_url=urls["poster"],
                    video_url=urls["video"],
                    original_url=urls["original"],
                    can_delete=can_delete_media(m, actor.user_id, can_moderate=mod),
                    can_moderate=mod,
                )
            )
        return out

    async def get(self, actor: Actor, media_id: UUID) -> MediaView:
        """One item (poll while processing); 404 when not visible."""
        media = await self._media(actor, media_id)
        return (await self.views(actor, [media]))[0]

    # ------------------------------------------------------------ albums ----

    async def _album_view(self, actor: Actor, album: Album) -> AlbumView:
        viewer = await self._viewer(actor, album.club_id, album.event_id)
        perms = await permissions(self._p, actor, album.club_id)
        blocked = await self._p.media.is_blocked(actor.user_id, album.club_id)
        counts = await self._p.albums.item_counts([album.id])
        items, folders = counts.get(album.id, (0, 0))
        return AlbumView(
            album=album,
            item_count=items,
            folder_count=folders,
            can_upload=can_upload_to_album(
                album,
                viewer,
                has_edit_events=Permission.EDIT_EVENTS in perms,
                blocked=blocked,
            ),
            can_moderate=Permission.MODERATE_MEDIA in perms,
        )

    async def list_albums(
        self, actor: Actor, club_id: UUID, parent_id: UUID | None = None
    ) -> list[AlbumView]:
        """Albums under a parent that the actor may see."""
        await load_club(self._p, club_id)
        if parent_id is not None:
            parent, _ = await self._album(actor, parent_id)
            if parent.club_id != club_id:
                raise ActivitiesNotFoundError()
        out: list[AlbumView] = []
        for album in await self._p.albums.list_children(club_id, parent_id):
            viewer = await self._viewer(actor, club_id, album.event_id)
            if can_view_album(album, viewer):
                out.append(await self._album_view(actor, album))
        return out

    async def get_album(self, actor: Actor, album_id: UUID) -> AlbumView:
        """One album with counters."""
        album, _ = await self._album(actor, album_id)
        return await self._album_view(actor, album)

    async def _depth(self, album: Album | None) -> int:
        """Depth of the parent chain (0 = no parent)."""
        depth = 0
        cur = album
        while cur is not None:
            depth += 1
            cur = (
                await self._p.albums.get(cur.parent_id)
                if cur.parent_id is not None
                else None
            )
        return depth

    async def create_album(
        self,
        actor: Actor,
        club_id: UUID,
        title: str,
        *,
        parent_id: UUID | None = None,
        event_id: UUID | None = None,
        visibility: AlbumVisibility = AlbumVisibility.SCHOOL,
        allow_download: bool = True,
        member_uploads: bool = False,
        description: str | None = None,
        event_date: date | None = None,
    ) -> AlbumView:
        """A folder (or an event album when ``event_id`` is given)."""
        perms = await permissions(self._p, actor, club_id)
        if Permission.EDIT_EVENTS not in perms:
            raise PermissionDeniedError()
        await load_club(self._p, club_id)
        title = title.strip()
        if not title:
            raise ClubInvalidError(params={"field": "title"})
        parent: Album | None = None
        if parent_id is not None:
            parent, _ = await self._album(actor, parent_id)
            if parent.club_id != club_id:
                raise ActivitiesNotFoundError()
        check_album_depth(await self._depth(parent))
        if event_id is not None:
            event = await load_event(self._p, event_id)
            if event.club_id != club_id:
                raise ActivitiesNotFoundError()
            if await self._p.albums.root_for_event(event_id) is not None:
                raise AlbumExistsError()
            event_date = event_date or event.starts_at.date()
        album = Album(
            id=uuid7(),
            club_id=club_id,
            title=title,
            visibility=visibility,
            allow_download=allow_download,
            member_uploads=member_uploads,
            event_id=event_id,
            parent_id=parent_id,
            description=description,
            event_date=event_date,
            created_by=actor.user_id,
            created_at=self._p.clock.now(),
        )
        await self._p.albums.add(album)
        await self._p.audit.record(actor.user_id, "activities.album.create", album.id)
        return await self._album_view(actor, album)

    async def event_album(self, actor: Actor, event_id: UUID) -> AlbumView | None:
        """The root album of an event if it exists and is visible, else None."""
        await load_event(self._p, event_id)
        album = await self._p.albums.root_for_event(event_id)
        if album is None:
            return None
        try:
            return await self.get_album(actor, album.id)
        except ActivitiesNotFoundError:
            return None

    async def ensure_event_album(self, actor: Actor, event_id: UUID) -> AlbumView:
        """The root album of an event, created on first use."""
        event = await load_event(self._p, event_id)
        existing = await self._p.albums.root_for_event(event_id)
        if existing is not None:
            return await self.get_album(actor, existing.id)
        return await self.create_album(
            actor,
            event.club_id,
            _title(event.title) or "Event",
            event_id=event_id,
            event_date=event.starts_at.date(),
        )

    async def update_album(  # noqa: C901 - one branch per optional field
        self,
        actor: Actor,
        album_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        visibility: AlbumVisibility | None = None,
        allow_download: bool | None = None,
        member_uploads: bool | None = None,
        event_date: date | None = None,
        cover_media_id: UUID | None = None,
    ) -> AlbumView:
        """Edit an album; settings need ``MODERATE_MEDIA``, texts ``EDIT_EVENTS``."""
        album, _ = await self._album(actor, album_id)
        perms = await permissions(self._p, actor, album.club_id)
        if Permission.EDIT_EVENTS not in perms:
            raise PermissionDeniedError()
        settings = (visibility, allow_download, member_uploads)
        if any(v is not None for v in settings):
            if Permission.MODERATE_MEDIA not in perms:
                raise PermissionDeniedError()
        if title is not None:
            if not title.strip():
                raise ClubInvalidError(params={"field": "title"})
            album.title = title.strip()
        if description is not None:
            album.description = description
        if event_date is not None:
            album.event_date = event_date
        if visibility is not None and visibility != album.visibility:
            album.visibility = visibility
            await self._p.audit.record(
                actor.user_id, "activities.album.visibility", album.id
            )
        if allow_download is not None:
            album.allow_download = allow_download
        if member_uploads is not None:
            album.member_uploads = member_uploads
        if cover_media_id is not None:
            cover = await self._p.media.get(cover_media_id)
            if cover is None or cover.album_id != album.id:
                raise ActivitiesNotFoundError()
            album.cover_media_id = cover.id
        await self._p.albums.save(album)
        return await self._album_view(actor, album)

    async def delete_album(self, actor: Actor, album_id: UUID) -> None:
        """Soft-delete an album with its folders and items."""
        album, _ = await self._album(actor, album_id)
        if not await self._is_moderator(actor, album.club_id):
            raise PermissionDeniedError()
        await self._delete_tree(album)
        await self._p.audit.record(actor.user_id, "activities.album.delete", album.id)

    async def _delete_tree(self, album: Album) -> None:
        now = self._p.clock.now()
        for child in await self._p.albums.list_children(album.club_id, album.id):
            await self._delete_tree(child)
        after: tuple[int, UUID] | None = None
        while True:
            batch = await self._p.media.list_album(
                album.id,
                statuses=frozenset(MediaStatus) - {MediaStatus.DELETED},
                kind=None,
                after=after,
                limit=200,
            )
            for m in batch:
                m.soft_delete(now)
                await self._save(m)
            if len(batch) < 200:
                break
            after = (batch[-1].position, batch[-1].id)
        album.delete(now)
        await self._p.albums.save(album)

    # ----------------------------------------------------------- uploads ----

    async def request_upload(  # noqa: C901 - quota and block checks in order
        self,
        actor: Actor,
        club_id: UUID,
        *,
        name: str,
        size: int,
        content_type: str,
        sha256_b64: str,
        consent_attested: bool,
        album_id: UUID | None = None,
        caption: str | None = None,
    ) -> UploadStarted:
        """Reserve an upload; the item is visible as soon as it is processed."""
        if not self._p.media_config.enabled:
            raise PermissionDeniedError()
        club = await load_club(self._p, club_id)
        perms = await permissions(self._p, actor, club_id)
        album: Album | None = None
        if album_id is not None:
            album, viewer = await self._album(actor, album_id)
            if album.club_id != club_id:
                raise ActivitiesNotFoundError()
            allowed = can_upload_to_album(
                album,
                viewer,
                has_edit_events=Permission.EDIT_EVENTS in perms,
                blocked=False,
            )
        else:
            allowed = bool(perms & {Permission.EDIT_EVENTS, Permission.ANNOUNCE})
        if not allowed:
            raise PermissionDeniedError()
        if await self._p.media.is_blocked(actor.user_id, club_id):
            raise MediaUploadBlockedError()
        if club.status != ClubStatus.ACTIVE:
            raise ClubStateError(params={"status": str(club.status)})
        if not consent_attested:
            raise MediaConsentRequiredError()
        try:
            await self._p.limiter.hit(
                f"activities:media-upload:{actor.user_id}",
                limit=self._p.media_config.uploads_per_hour,
                window_seconds=3600,
            )
        except RateLimitedError as exc:
            raise MediaRateLimitedError() from exc
        kind = kind_for_content_type(content_type)
        if kind_for_name(name) != kind:
            raise MediaTypeNotAllowedError(params={"content_type": content_type})
        sha_hex = _sha_hex(sha256_b64)
        limits = await self._limits(club_id)
        check_size(kind, size, limits)
        check_quota(await self._p.media.used_bytes_locked(club_id), size, limits)
        position = 0
        if album is not None:
            if await self._p.media.count_album(album.id) >= limits.album_items_max:
                raise MediaQuotaExceededError(
                    params={"album_items_max": limits.album_items_max}
                )
            dup = await self._p.media.find_duplicate(album.id, sha_hex)
            if dup is not None:
                raise MediaDuplicateError(params={"media_id": str(dup.id)})
            position = await self._p.media.next_position(album.id)
        ticket = await self._p.media_store.request_upload(
            club_id=club_id,
            name=name,
            size=size,
            content_type=content_type,
            sha256_b64=sha256_b64,
            max_bytes=check_size_limit(kind, limits),
        )
        now = self._p.clock.now()
        media = Media(
            id=uuid7(),
            club_id=club_id,
            kind=kind,
            uploaded_by=actor.user_id,
            original_file_id=ticket.file_id,
            usage=MediaUsage.ALBUM if album else MediaUsage.STAGED,
            status=MediaStatus.UPLOADING,
            album_id=album.id if album else None,
            byte_size=size,
            content_sha256=sha_hex,
            caption=caption,
            position=position,
            consent_attested=True,
            created_at=now,
            updated_at=now,
        )
        await self._p.media.add(media)
        await self._p.audit.record(actor.user_id, "activities.media.upload", media.id)
        return UploadStarted(media, ticket.url, ticket.method, ticket.headers)

    async def complete(self, actor: Actor, media_id: UUID) -> MediaView:
        """The bytes are uploaded: verify them and queue processing. Repeatable."""
        media = await self._p.media.get(media_id)
        if (
            media is None
            or media.uploaded_by != actor.user_id
            or media.status == MediaStatus.DELETED
        ):
            raise ActivitiesNotFoundError()
        if media.status == MediaStatus.UPLOADING:
            assert media.original_file_id is not None
            stored = await self._p.media_store.complete(media.original_file_id)
            bad = (
                stored.status == "rejected"
                or stored.byte_size != media.byte_size
                or (stored.sha256 is not None and stored.sha256 != media.content_sha256)
            )
            if bad:
                await self._p.media_store.delete(media.original_file_id)
                await self._p.media.remove(media.id)
                raise MediaUploadMismatchError()
            used = await self._p.media.used_bytes_locked(media.club_id)
            limits = await self._limits(media.club_id)
            try:
                check_quota(used - media.byte_size, media.byte_size, limits)
            except MediaQuotaExceededError:
                await self._p.media_store.delete(media.original_file_id)
                await self._p.media.remove(media.id)
                raise
            media.mark_processing()
            await self._save(media)
            await self._p.media_kicker.process(media.id)
        return (await self.views(actor, [media]))[0]

    async def process(self, media_id: UUID) -> None:
        """Worker: sniff, derive, store; the item becomes ready or failed."""
        media = await self._p.media.get(media_id)
        if (
            media is None
            or media.status != MediaStatus.PROCESSING
            or media.original_file_id is None
        ):
            return
        work = Path(tempfile.mkdtemp(prefix="club-media-"))
        stored: list[UUID] = []
        try:
            source = work / "original"
            await self._p.media_store.download_to(media.original_file_id, str(source))
            proc = self._p.media_processor
            try:
                probe = await proc.probe(source)
                if probe.kind != media.kind:
                    raise MediaKindError()
                derivs = await proc.make_derivatives(source, probe, work / "out")
            except (MediaTypeNotAllowedError, MediaTooLargeError, MediaKindError):
                media.mark_failed()
                await self._save(media)
                await self._p.media_store.delete(media.original_file_id)
                media.original_file_id = None
                await self._save(media)
                return
            ids: dict[MediaVariant, UUID] = {}
            total = source.stat().st_size
            for d in derivs:
                fid = await self._p.media_store.store_path(
                    club_id=media.club_id,
                    name=f"{media.id}-{d.variant.value}{d.path.suffix}",
                    path=str(d.path),
                    content_type=d.content_type,
                )
                stored.append(fid)
                ids[d.variant] = fid
                total += d.path.stat().st_size
            thumb = ids.get(MediaVariant.THUMB) or ids.get(MediaVariant.POSTER)
            # a video's playable copy is kept in preview_file_id
            preview = ids.get(MediaVariant.PREVIEW) or ids.get(MediaVariant.VIDEO)
            if thumb is None or preview is None:
                raise MediaStateError()
            media.mark_ready(
                thumb_file_id=thumb,
                preview_file_id=preview,
                poster_file_id=ids.get(MediaVariant.POSTER),
                byte_size=total,
                width=probe.width,
                height=probe.height,
                duration_ms=probe.duration_ms,
            )
            await self._save(media)
            stored = []
        finally:
            for fid in stored:
                await self._p.media_store.delete(fid)
            shutil.rmtree(work, ignore_errors=True)

    # ------------------------------------------------------- album items ----

    async def list_media(
        self,
        actor: Actor,
        album_id: UUID,
        *,
        kind: MediaKind | None = None,
        cursor: str | None = None,
        limit: int = ALBUM_PAGE,
    ) -> MediaPage:
        """A page of an album ordered by ``(position, id)``."""
        album, _ = await self._album(actor, album_id)
        limit = max(1, min(limit, 200))
        after: tuple[int, UUID] | None = None
        if cursor:
            try:
                pos, _, mid = cursor.partition(":")
                after = (int(pos), UUID(mid))
            except ValueError as exc:
                raise ActivitiesNotFoundError() from exc
        moderator = await self._is_moderator(actor, album.club_id)
        rows = await self._p.media.list_album(
            album.id,
            statuses=_STAFF_STATUSES if moderator else _PUBLIC_STATUSES,
            kind=kind,
            after=after,
            limit=limit + 1,
        )
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = f"{rows[-1].position}:{rows[-1].id}" if more and rows else None
        return MediaPage(await self.views(actor, rows), nxt)

    async def update(
        self, actor: Actor, media_id: UUID, *, caption: str | None = None
    ) -> MediaView:
        """Edit the caption (uploader or moderator)."""
        media = await self._media(actor, media_id)
        await self._require_owner_or_mod(actor, media)
        if caption is not None:
            media.caption = caption.strip()[:300] or None
        await self._save(media)
        return (await self.views(actor, [media]))[0]

    async def _require_owner_or_mod(self, actor: Actor, media: Media) -> bool:
        mod = await self._is_moderator(actor, media.club_id)
        if not can_delete_media(media, actor.user_id, can_moderate=mod):
            raise PermissionDeniedError()
        return mod

    async def attach(self, actor: Actor, media_id: UUID, album_id: UUID) -> MediaView:
        """Put a staged item into an album."""
        media = await self._media(actor, media_id)
        album, viewer = await self._album(actor, album_id)
        if album.club_id != media.club_id:
            raise ActivitiesNotFoundError()
        await self._require_owner_or_mod(actor, media)
        perms = await permissions(self._p, actor, album.club_id)
        if not can_upload_to_album(
            album,
            viewer,
            has_edit_events=Permission.EDIT_EVENTS in perms,
            blocked=await self._p.media.is_blocked(actor.user_id, album.club_id),
        ):
            raise PermissionDeniedError()
        await self._place(media, album)
        return (await self.views(actor, [media]))[0]

    async def _place(self, media: Media, album: Album) -> None:
        if media.album_id == album.id:
            return
        if media.content_sha256 and await self._p.media.find_duplicate(
            album.id, media.content_sha256
        ):
            raise MediaDuplicateError()
        media.attach_to_album(album.id, await self._p.media.next_position(album.id))
        await self._save(media)

    async def move(
        self, actor: Actor, media_ids: list[UUID], album_id: UUID
    ) -> list[MediaView]:
        """Move items of one club to another album of the same club."""
        album, _ = await self._album(actor, album_id)
        if not await self._is_moderator(actor, album.club_id):
            perms = await permissions(self._p, actor, album.club_id)
            if Permission.EDIT_EVENTS not in perms:
                raise PermissionDeniedError()
        moved: list[Media] = []
        for mid in media_ids:
            media = await self._media(actor, mid)
            if media.club_id != album.club_id:
                raise ActivitiesNotFoundError()
            if media.album_id != album.id and media.usage == MediaUsage.ALBUM:
                if await self._p.media.find_duplicate(album.id, media.content_sha256):
                    raise MediaDuplicateError()
                media.album_id = album.id
                media.position = await self._p.media.next_position(album.id)
                await self._save(media)
            elif media.usage != MediaUsage.ALBUM:
                await self._place(media, album)
            moved.append(media)
        return await self.views(actor, moved)

    async def delete(self, actor: Actor, media_id: UUID) -> None:
        """Soft-delete by the uploader or a moderator; the purge job removes files."""
        media = await self._media(actor, media_id)
        await self._require_owner_or_mod(actor, media)
        media.soft_delete(self._p.clock.now())
        await self._save(media)
        await self._p.audit.record(actor.user_id, "activities.media.delete", media.id)

    async def undelete(self, actor: Actor, media_id: UUID) -> MediaView:
        """Undo a delete inside the grace window."""
        media = await self._p.media.get(media_id)
        if media is None or media.status != MediaStatus.DELETED:
            raise ActivitiesNotFoundError()
        if media.original_file_id is None:
            raise ActivitiesNotFoundError()
        mod = await self._is_moderator(actor, media.club_id)
        if not can_delete_media(media, actor.user_id, can_moderate=mod):
            raise ActivitiesNotFoundError()
        limits = await self._limits(media.club_id)
        used = await self._p.media.used_bytes_locked(media.club_id)
        check_quota(used, media.byte_size, limits)
        media.undelete()
        await self._save(media)
        return (await self.views(actor, [media]))[0]

    async def set_hidden(
        self,
        actor: Actor,
        media_id: UUID,
        hidden: bool,
        reason: str | None = None,
    ) -> MediaView:
        """Hide or show an item; moderators any, the uploader only an own hide."""
        media = await self._media(actor, media_id)
        mod = await self._require_owner_or_mod(actor, media)
        if hidden:
            media.hide(
                by=actor.user_id,
                reason=reason,
                source=HiddenSource.MODERATOR if mod else HiddenSource.UPLOADER,
            )
        else:
            media.restore(by_moderator=mod, by=actor.user_id)
        await self._save(media)
        await self._p.audit.record(
            actor.user_id,
            "activities.media.hide" if hidden else "activities.media.restore",
            media.id,
        )
        return (await self.views(actor, [media]))[0]

    # ------------------------------------------------------ announcements ---

    async def stage_for(
        self, actor: Actor, club_id: UUID, media_ids: list[UUID]
    ) -> list[Media]:
        """Photos usable as attachments: staged, ready, same club, own or moderated."""
        out: list[Media] = []
        mod = await self._is_moderator(actor, club_id)
        for mid in dict.fromkeys(media_ids):
            m = await self._p.media.get(mid)
            if m is None or m.club_id != club_id or m.status == MediaStatus.DELETED:
                raise ActivitiesNotFoundError()
            if m.uploaded_by != actor.user_id and not mod:
                raise ActivitiesNotFoundError()
            if m.kind != MediaKind.PHOTO:
                raise MediaKindError()
            out.append(m)
        return out

    # ------------------------------------------------------------ reports ---

    async def report(
        self, actor: Actor, media_id: UUID, *, reason: str, is_subject: bool
    ) -> MediaReport:
        """Report an item; "I am in this photo" hides it at once."""
        media = await self._media(actor, media_id)
        existing = frozenset(
            r.reporter_id for r in await self._p.media.reports_for(media.id)
        )
        report = media.report(
            actor.user_id,
            is_subject=is_subject,
            reason=reason,
            existing_reporters=existing,
            report_id=uuid7(),
            now=self._p.clock.now(),
        )
        await self._save(media)
        await self._p.media.add_report(report)
        await self._p.audit.record(actor.user_id, "activities.media.report", media.id)
        return report

    async def review_queue(
        self,
        actor: Actor,
        *,
        state: str = "reported",
        club_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewPage:
        """Items awaiting review (``reported`` or ``hidden``)."""
        if club_id is None:
            self._require_global(actor)
        elif not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        items, total = await self._p.media.list_for_review(
            state, club_id, max(1, min(limit, 200)), max(0, offset)
        )
        reports = {m.id: list(await self._p.media.reports_for(m.id)) for m in items}
        return ReviewPage(await self.views(actor, items), reports, total)

    async def resolve_report(
        self, actor: Actor, report_id: UUID, *, upheld: bool
    ) -> MediaView:
        """Close a report; upholding it hides the item, dismissing may restore it."""
        report = await self._p.media.get_report(report_id)
        media = await self._p.media.get(report.media_id) if report else None
        if report is None or media is None:
            raise ActivitiesNotFoundError()
        if not await self._is_moderator(actor, media.club_id):
            raise PermissionDeniedError()
        report.resolve(upheld, actor.user_id, self._p.clock.now())
        await self._p.media.save_report(report)
        if upheld and media.status == MediaStatus.READY:
            media.hide(
                by=actor.user_id,
                reason=report.reason or None,
                source=HiddenSource.MODERATOR,
            )
        elif not upheld and media.status == MediaStatus.HIDDEN:
            still_open = [
                r
                for r in await self._p.media.reports_for(media.id)
                if r.status.value == "open"
            ]
            if not still_open and media.hidden_source == HiddenSource.REPORT:
                media.restore(by_moderator=True, by=actor.user_id)
        await self._save(media)
        await self._p.audit.record(
            actor.user_id,
            (
                "activities.media.report-upheld"
                if upheld
                else "activities.media.report-dismissed"
            ),
            media.id,
        )
        return (await self.views(actor, [media]))[0]

    async def purge_now(self, actor: Actor, media_id: UUID) -> None:
        """A moderator removes an item and its files at once."""
        media = await self._p.media.get(media_id)
        if media is None or not await self._is_moderator(actor, media.club_id):
            raise ActivitiesNotFoundError()
        media.soft_delete(self._p.clock.now())
        await self._remove_files(media)
        await self._save(media)
        await self._p.audit.record(actor.user_id, "activities.media.purge", media.id)

    # ----------------------------------------------------------- blocks -----

    async def block_uploader(
        self,
        actor: Actor,
        user_id: UUID,
        *,
        club_id: UUID | None = None,
        reason: str = "",
    ) -> MediaBlock:
        """Bar a user from uploading (one club, or everywhere for platform staff)."""
        if club_id is None:
            self._require_global(actor)
        elif not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        block = MediaBlock(
            id=uuid7(),
            user_id=user_id,
            club_id=club_id,
            reason=reason.strip()[:500],
            created_by=actor.user_id,
            created_at=self._p.clock.now(),
        )
        await self._p.media.add_block(block)
        await self._p.audit.record(actor.user_id, "activities.media.block", user_id)
        return block

    async def unblock_uploader(
        self, actor: Actor, user_id: UUID, *, club_id: UUID | None = None
    ) -> None:
        """Lift a block."""
        if club_id is None:
            self._require_global(actor)
        elif not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        await self._p.media.remove_block(user_id, club_id)
        await self._p.audit.record(actor.user_id, "activities.media.unblock", user_id)

    async def list_blocks(
        self, actor: Actor, club_id: UUID | None = None
    ) -> list[MediaBlock]:
        """Blocks of a club (None = global ones)."""
        if club_id is None:
            self._require_global(actor)
        elif not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        return await self._p.media.list_blocks(club_id)

    # ------------------------------------------------------- usage/limits ---

    async def usage(self, actor: Actor, club_id: UUID) -> MediaUsageView:
        """Quota use of the club (organizers and moderators)."""
        await load_club(self._p, club_id)
        perms = await permissions(self._p, actor, club_id)
        if not perms & {Permission.EDIT_EVENTS, Permission.MODERATE_MEDIA}:
            raise PermissionDeniedError()
        limits = await self._limits(club_id)
        return MediaUsageView(
            used_bytes=await self._p.media.used_bytes(club_id),
            quota_bytes=limits.quota_bytes,
            item_count=await self._p.media.item_count(club_id),
            photo_max_bytes=limits.photo_max_bytes,
            video_max_bytes=limits.video_max_bytes,
            overrides=await self._p.media.overrides(club_id),
        )

    async def set_club_limits(
        self,
        actor: Actor,
        club_id: UUID,
        *,
        photo_max_bytes: int | None = None,
        video_max_bytes: int | None = None,
        quota_bytes: int | None = None,
    ) -> MediaUsageView:
        """Replace the club's overrides (platform staff); ``None`` clears one."""
        self._require_global(actor)
        await load_club(self._p, club_id)
        values = (photo_max_bytes, video_max_bytes, quota_bytes)
        if any(v is not None and v < 1 for v in values):
            raise ClubInvalidError(params={"field": "media_limits"})
        await self._p.media.set_overrides(
            club_id, ClubMediaOverrides(photo_max_bytes, video_max_bytes, quota_bytes)
        )
        await self._p.audit.record(actor.user_id, "activities.media.limits", club_id)
        return await self.usage(actor, club_id)

    # -------------------------------------------------------------- jobs ----

    async def _remove_files(self, media: Media) -> None:
        for fid in (
            media.original_file_id,
            media.thumb_file_id,
            media.preview_file_id,
            media.poster_file_id,
        ):
            if fid is not None:
                await self._p.media_store.delete(fid)
        media.original_file_id = None
        media.thumb_file_id = None
        media.preview_file_id = None
        media.poster_file_id = None
        media.byte_size = 0

    # ---------------------------------------------------- signed serving ----

    async def open_variant(
        self, media_id: UUID, variant: MediaVariant, exp: int, signature: str
    ) -> ServedVariant:
        """Check a signed URL against the item's live state; 404 for anything wrong.

        Every open re-checks that the item is served (not hidden, deleted or
        hidden by a report) and that its album, club and audience still match
        what the URL was signed for.
        """
        media = await self._p.media.get(media_id)
        if media is None or not media.is_served:
            raise ActivitiesNotFoundError()
        audience = await self._audience(media)
        if audience is None:
            raise ActivitiesNotFoundError()
        try:
            verify_media_url(
                self._url_secret(audience),
                media_id,
                variant,
                exp,
                signature,
                self._p.clock.now(),
            )
        except InvalidMediaUrlError as exc:
            raise ActivitiesNotFoundError() from exc
        video = media.kind == MediaKind.VIDEO
        file_id = {
            MediaVariant.THUMB: media.thumb_file_id,
            MediaVariant.PREVIEW: None if video else media.preview_file_id,
            MediaVariant.POSTER: media.poster_file_id,
            MediaVariant.VIDEO: media.preview_file_id if video else None,
            MediaVariant.ORIGINAL: media.original_file_id,
        }[variant]
        if file_id is None:
            raise ActivitiesNotFoundError()
        streamed = variant in _STREAMED
        return ServedVariant(
            file_id=file_id,
            redirect=not streamed,
            content_type="image/webp" if streamed else "application/octet-stream",
        )

    async def read_variant(self, file_id: UUID) -> bytes:
        """Bytes of a small derivative (after ``open_variant``)."""
        return await self._p.media_store.read_bytes(file_id)

    async def variant_url(self, file_id: UUID) -> str:
        """Short-lived presigned GET for a video or an original."""
        return await self._p.media_store.download_url(
            file_id, ttl_seconds=REDIRECT_TTL_SECONDS
        )

    async def purge(self) -> int:
        """Hourly: drop expired soft deletes, stale staged and stuck uploads."""
        c = self._p.media_config
        now = self._p.clock.now()
        done = 0
        for m in await self._p.media.list_deleted_before(
            now - timedelta(days=c.purge_after_days)
        ):
            await self._remove_files(m)
            await self._save(m)
            done += 1
        found = [
            *await self._p.media.list_stale(
                True, MediaStatus.READY, now - timedelta(hours=c.staged_ttl_hours)
            ),
            *await self._p.media.list_stale(
                False,
                MediaStatus.UPLOADING,
                now - timedelta(hours=c.uploading_ttl_hours),
            ),
        ]
        stale = {m.id: m for m in found}.values()
        for m in stale:
            m.soft_delete(now)
            await self._remove_files(m)
            await self._save(m)
            done += 1
        return done

    # ------------------------------------------------------------ import ----

    async def upsert_album(
        self,
        actor: Actor,
        club_id: UUID,
        *,
        source_ref: str,
        title: str,
        parent_id: UUID | None = None,
        description: str | None = None,
        event_date: date | None = None,
        visibility: AlbumVisibility = AlbumVisibility.SCHOOL,
    ) -> Album:
        """Import: one album per ``source_ref``; a repeat updates it in place."""
        if not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        await load_club(self._p, club_id)
        existing = await self._p.albums.get_by_source_ref(source_ref)
        if existing is not None:
            if existing.club_id != club_id:
                raise ActivitiesNotFoundError()
            existing.title = title.strip() or existing.title
            existing.description = description
            existing.event_date = event_date
            await self._p.albums.save(existing)
            return existing
        parent = await self._p.albums.get(parent_id) if parent_id else None
        check_album_depth(await self._depth(parent))
        album = Album(
            id=uuid7(),
            club_id=club_id,
            title=title.strip(),
            visibility=visibility,
            parent_id=parent_id,
            description=description,
            event_date=event_date,
            source_ref=source_ref,
            created_by=actor.user_id,
            created_at=self._p.clock.now(),
        )
        await self._p.albums.add(album)
        return album

    async def imported_media(
        self, actor: Actor, club_id: UUID, source_ref: str
    ) -> Media | None:
        """Import: the item already imported under source_ref in this club, or None."""
        if not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        m = await self._p.media.get_by_source_ref(source_ref)
        return m if m is not None and m.club_id == club_id else None

    async def import_media(
        self,
        actor: Actor,
        club_id: UUID,
        album_id: UUID,
        *,
        source_ref: str,
        kind: MediaKind,
        original_file_id: UUID,
        byte_size: int,
        sha256_hex: str,
        caption: str | None = None,
    ) -> tuple[Media, bool]:
        """Import an already stored original; ``(item, created)``, idempotent."""
        if not await self._is_moderator(actor, club_id):
            raise PermissionDeniedError()
        existing = await self._p.media.get_by_source_ref(source_ref)
        if existing is not None:
            return existing, False
        album = await self._p.albums.get(album_id)
        if album is None or album.club_id != club_id or album.is_deleted:
            raise ActivitiesNotFoundError()
        now = self._p.clock.now()
        media = Media(
            id=uuid7(),
            club_id=club_id,
            kind=kind,
            uploaded_by=None,
            original_file_id=original_file_id,
            usage=MediaUsage.ALBUM,
            status=MediaStatus.PROCESSING,
            album_id=album_id,
            byte_size=byte_size,
            content_sha256=sha256_hex,
            caption=caption,
            position=await self._p.media.next_position(album_id),
            imported=True,
            source_ref=source_ref,
            created_at=now,
            updated_at=now,
        )
        await self._p.media.add(media)
        await self._p.media_kicker.process(media.id)
        return media, True


def check_size_limit(kind: MediaKind, limits: MediaLimits) -> int:
    """The byte cap of one file of this kind."""
    return limits.photo_max_bytes if kind == MediaKind.PHOTO else limits.video_max_bytes
