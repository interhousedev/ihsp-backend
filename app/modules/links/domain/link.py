"""The Link entity: every public pointer on the short link host."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LinkKind(StrEnum):
    """What a link points to."""

    URL = "url"
    FILE = "file"
    CHAT = "chat"
    FLASHCARD_SET = "flashcard_set"
    ARTIFACT = "artifact"


class LessonRole(StrEnum):
    """Role of a lesson resource."""

    MATERIAL = "material"
    ATTACHMENT = "attachment"
    HOMEWORK = "homework"


class ShareMode(StrEnum):
    """Whether a shared chat shows later messages."""

    SNAPSHOT = "snapshot"
    LIVE = "live"


class LinkState(StrEnum):
    """What a visitor sees when opening the link."""

    ACTIVE = "active"
    GONE = "gone"
    DISABLED = "disabled"


SHORT_KINDS = (LinkKind.URL, LinkKind.FILE)
SHARE_KINDS = (LinkKind.CHAT, LinkKind.FLASHCARD_SET, LinkKind.ARTIFACT)


@dataclass(slots=True)
class Link:
    """A short link, a share or a lesson resource."""

    id: UUID
    slug: str
    kind: LinkKind
    owner_id: UUID
    created_at: datetime
    target_url: str | None = None
    file_id: UUID | None = None
    target_id: UUID | None = None
    title: str | None = None
    lesson_id: UUID | None = None
    lesson_role: LessonRole | None = None
    share_mode: ShareMode | None = None
    snapshot_seq: int | None = None
    expires_at: datetime | None = None
    hits: int = 0
    last_hit_at: datetime | None = None
    hidden_at: datetime | None = None
    hidden_by: UUID | None = None
    disabled_at: datetime | None = None
    disabled_by: UUID | None = None
    disabled_reason: str | None = None
    revoked_at: datetime | None = None
    reports: int = 0
    last_reported_at: datetime | None = None
    reports_reviewed_at: datetime | None = None
    slug_released_at: datetime | None = None

    @property
    def is_share(self) -> bool:
        """True for shared chats and flash card sets."""
        return self.kind in SHARE_KINDS

    @property
    def is_hidden(self) -> bool:
        """True while a lesson resource is hidden by the teacher."""
        return self.hidden_at is not None

    @property
    def is_disabled(self) -> bool:
        """True after Administration disabled the link."""
        return self.disabled_at is not None

    @property
    def is_revoked(self) -> bool:
        """True after the owner deleted or revoked the link."""
        return self.revoked_at is not None

    def state(self, now: datetime) -> LinkState:
        """Return gone (revoked or expired), disabled or active."""
        if self.revoked_at is not None:
            return LinkState.GONE
        if self.expires_at is not None and self.expires_at <= now:
            return LinkState.GONE
        if self.disabled_at is not None:
            return LinkState.DISABLED
        return LinkState.ACTIVE

    def is_listed_resource(self, *, include_hidden: bool) -> bool:
        """True if the link shows up as a lesson resource."""
        if self.lesson_id is None or self.revoked_at is not None:
            return False
        if self.disabled_at is not None:
            return False
        return include_hidden or self.hidden_at is None

    def revoke(self, now: datetime) -> None:
        """Mark the link deleted or revoked; keeps the first revocation time."""
        if self.revoked_at is None:
            self.revoked_at = now

    def disable(self, by: UUID, reason: str, now: datetime) -> None:
        """Disable the link (moderation) and mark its reports as reviewed."""
        self.disabled_at = now
        self.disabled_by = by
        self.disabled_reason = reason
        self.reports_reviewed_at = now

    def hide(self, by: UUID, now: datetime) -> None:
        """Hide a lesson resource from students and the room page."""
        self.hidden_at = now
        self.hidden_by = by

    def unhide(self) -> None:
        """Show a hidden lesson resource again."""
        self.hidden_at = None
        self.hidden_by = None

    def register_report(self, now: datetime) -> None:
        """Count one report from a visitor."""
        self.reports += 1
        self.last_reported_at = now

    def dismiss_reports(self, now: datetime) -> None:
        """Mark the current reports as reviewed."""
        self.reports_reviewed_at = now

    @property
    def needs_review(self) -> bool:
        """True if the link belongs in the moderation queue."""
        if self.reports <= 0 or self.last_reported_at is None:
            return False
        reviewed = self.reports_reviewed_at
        return reviewed is None or reviewed < self.last_reported_at
