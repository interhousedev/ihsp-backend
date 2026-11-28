"""Ports to other modules and to infrastructure."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.modules.activities.domain.media import MediaKind, MediaVariant
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.shared.actor import Role
from app.shared.contracts.club_courses import CourseDirectory  # noqa: F401
from app.shared.notifications import NotificationDraft


class Notifier(Protocol):
    """Writes notifications; the recipient's settings choose the channel."""

    async def send(self, drafts: list[NotificationDraft]) -> None:
        """Queue notifications; a repeated dedupe key is dropped."""

    async def cancel_scheduled(
        self, prefix: str, *, user_id: UUID | None = None
    ) -> None:
        """Drop pending rows whose dedupe key starts with the prefix."""


class UserDirectory(Protocol):
    """What the module needs to know about people."""

    async def display_name(self, user_id: UUID) -> str:
        """Display name."""

    async def age(self, user_id: UUID) -> int | None:
        """Age in years when known."""

    async def is_student(self, user_id: UUID) -> bool:
        """Whether the person is a student."""

    async def holders(self, role: Role) -> list[UUID]:
        """People holding a global role."""

    async def graduating(self) -> set[UUID]:
        """Students in their final year."""


class Captcha(Protocol):
    """Bot check."""

    async def verify(self, token: str, ip: str) -> bool:
        """True when the token is valid."""


class ContactRelay(Protocol):
    """Delivers a visitor's message to a club owner's Telegram; nothing is stored."""

    async def reachable(self, user_id: UUID) -> bool:
        """Whether the person has a Telegram chat the bot can write to."""

    async def deliver(
        self, user_id: UUID, *, club_slug: str, name: str, email: str, body: str
    ) -> bool:
        """Send the message; False when no chat accepted it."""


class RateLimiter(Protocol):
    """Fixed-window limiter; raises `RateLimitedError` over the limit."""

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        """Count one hit."""


class AuditLog(Protocol):
    """Audit trail."""

    async def record(self, actor_id: UUID, action: str, target: UUID | None) -> None:
        """Write one audit row."""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """An entry of the ONE opportunities catalog and where it is shown."""

    id: UUID
    draft: OpportunityDraft
    audience: frozenset[str]
    archived: bool
    lock_version: int

    @property
    def title(self) -> str:
        """Entry title."""
        return self.draft.title

    @property
    def kind(self) -> str:
        """Entry kind."""
        return self.draft.kind


class OpportunityCatalog(Protocol):
    """The admission catalog with the `audience` column (`admission`, `my_iht`)."""

    async def get(self, opportunity_id: UUID) -> CatalogEntry | None:
        """One entry."""

    async def list_all(self) -> list[CatalogEntry]:
        """Every entry."""

    async def references_ok(self, draft: OpportunityDraft) -> str | None:
        """The first invalid reference field (taxonomy, course, org) or None."""

    async def apply(
        self,
        draft: OpportunityDraft,
        audience: frozenset[str],
        *,
        target_id: UUID | None,
        by: UUID,
    ) -> UUID:
        """Create or overwrite an entry; an update bumps the lock version."""

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        """Hide or restore."""

    async def in_use(self, opportunity_id: UUID) -> bool:
        """Whether student plans or comments refer to it."""

    async def delete(self, opportunity_id: UUID) -> None:
        """Remove an unused entry."""


@dataclass(frozen=True, slots=True)
class MediaConfig:
    """Settings defaults for club media (``IHSP_ACTIVITIES__MEDIA_*``)."""

    enabled: bool = True
    photo_max_bytes: int = 15 * 1024 * 1024
    video_max_bytes: int = 300 * 1024 * 1024
    quota_bytes: int = 5 * 1024**3
    announcement_photos_max: int = 10
    album_items_max: int = 500
    uploads_per_hour: int = 200
    url_bucket_hours: int = 1
    purge_after_days: int = 7
    staged_ttl_hours: int = 24
    uploading_ttl_hours: int = 1


@dataclass(frozen=True, slots=True)
class UploadTicket:
    """A reserved file and the presigned PUT the browser sends the bytes to."""

    file_id: UUID
    url: str
    method: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class StoredFile:
    """What the files module knows about a file.

    ``sha256`` is lowercase hex (``None`` when unknown); ``status`` is the files
    status (``rejected`` means verification failed).
    """

    id: UUID
    owner_id: UUID
    name: str
    content_type: str
    byte_size: int
    status: str
    sha256: str | None = None


class MediaStore(Protocol):
    """Club-owned files (``FileScope.CLUB``, ``FilePurpose.CLUB_MEDIA``)."""

    async def request_upload(
        self,
        *,
        club_id: UUID,
        name: str,
        size: int,
        content_type: str,
        sha256_b64: str,
        max_bytes: int,
    ) -> UploadTicket:
        """Reserve a file owned by the club."""

    async def complete(self, file_id: UUID) -> StoredFile:
        """Verify the uploaded object (size, checksum, sniffed type)."""

    async def info(self, file_id: UUID) -> StoredFile | None:
        """Metadata of any file (used to vet a club logo), or None."""

    async def download_to(self, file_id: UUID, path: str) -> None:
        """Stream the file to ``path`` on disk."""

    async def store_path(
        self, *, club_id: UUID, name: str, path: str, content_type: str
    ) -> UUID:
        """Store a derivative from disk as a club file; returns its id."""

    async def read_bytes(self, file_id: UUID) -> bytes:
        """The whole file (small derivatives only)."""

    async def download_url(self, file_id: UUID, *, ttl_seconds: int) -> str:
        """A presigned GET URL."""

    async def delete(self, file_id: UUID) -> None:
        """Remove the file and its object; unknown ids are ignored."""

    async def adopt(self, file_ids: list[UUID], club_id: UUID) -> None:
        """Give files to the club (a logo): the uploader's quota stops counting."""


@dataclass(frozen=True, slots=True)
class MediaProbe:
    """What the content really is (decided by sniffing, never by the name)."""

    kind: MediaKind
    content_type: str
    width: int
    height: int
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class Derivative:
    """A generated file on disk."""

    variant: MediaVariant
    path: Path
    content_type: str
    width: int | None = None
    height: int | None = None


class MediaProcessor(Protocol):
    """Makes derivatives: EXIF-stripped, oriented, re-encoded thumb/preview/poster.

    Implemented by ``PillowFfmpegMediaProcessor``. ``probe`` raises
    ``MediaTypeNotAllowedError`` / ``MediaTooLargeError`` for an unusable original;
    the service then marks the item failed.
    """

    async def probe(self, path: Path) -> MediaProbe:
        """Sniff the real type; read dimensions and duration."""

    async def make_derivatives(
        self, path: Path, probe: MediaProbe, out_dir: Path
    ) -> list[Derivative]:
        """Write derivatives into ``out_dir`` and return them."""


class MediaKicker(Protocol):
    """Queues the background processing job."""

    async def process(self, media_id: UUID) -> None:
        """Run the media worker's processing of ``media_id``."""
