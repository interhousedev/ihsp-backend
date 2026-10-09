"""Reports, sanctions and suggestions (doc §§ 3.4, 3.6): the moderation records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.enums import (
    ReportReason,
    ReportStatus,
    SanctionKind,
    SuggestionStatus,
    UploaderRole,
)
from app.modules.library.domain.moderation_rules import ReportSignal


@dataclass(slots=True)
class Report:
    """One user's report about an item. Nothing here is ever shown to the uploader."""

    id: UUID
    item_id: UUID
    reporter_id: UUID
    reporter_role: UploaderRole
    reason: ReportReason
    created_at: datetime
    text: str | None = None
    status: ReportStatus = ReportStatus.OPEN
    handled_by: UUID | None = None
    handled_at: datetime | None = None
    action: str | None = None

    @property
    def signal(self) -> ReportSignal:
        """The part the auto-hold rule reads."""
        return ReportSignal(self.reporter_id, self.reporter_role, self.reason)


@dataclass(frozen=True, slots=True)
class Sanction:
    """A warning or an upload ban; a ban is active until `until` (forever if None)."""

    id: UUID
    user_id: UUID
    kind: SanctionKind
    reason: str
    set_by: UUID
    created_at: datetime
    until: datetime | None = None
    item_id: UUID | None = None

    def is_active_ban(self, now: datetime) -> bool:
        """True for an upload ban that has not run out."""
        return self.kind is SanctionKind.UPLOAD_BAN and (
            self.until is None or self.until > now
        )


@dataclass(slots=True)
class BookSuggestion:
    """A book a teacher or student suggests; waits in the librarian queue."""

    id: UUID
    user_id: UUID
    title: str
    created_at: datetime
    url: str | None = None
    file_id: UUID | None = None
    note: str | None = None
    status: SuggestionStatus = SuggestionStatus.NEW
    handled_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReportGroup:
    """Open reports of one reason on one item: how many, and their ids."""

    item_id: UUID
    reason: ReportReason
    count: int
    report_ids: tuple[UUID, ...]
    first_at: datetime


@dataclass(frozen=True, slots=True)
class QueueAgeStats:
    """Waiting time of the review queue (materials in `pending_review`)."""

    length: int
    oldest_age_hours: float | None
    average_hours: float | None
