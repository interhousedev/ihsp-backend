"""Documents, checklist, deadlines, reminders and transcript requests (§6, §12)."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.admission.domain.transitions import check_transition
from app.modules.admission.domain.workflow import (
    TRANSCRIPT_TRANSITIONS,
    DocumentKind,
    DocumentVisibility,
    ReviewStatus,
    ScanStatus,
    TranscriptStatus,
)

TASHKENT: Final = ZoneInfo("Asia/Tashkent")
REJECT_NOTE_LIMIT: Final = 300
DESTINATION_NOTE_LIMIT: Final = 200
PICKUP_LIMIT: Final = 200
SIGNED_URL_MAX_SECONDS: Final = 300
REMIND_COOLDOWN: Final = dt.timedelta(hours=24)
REMINDER_CATCH_UP: Final = dt.timedelta(hours=24)
REMINDER_OFFSETS: Final = (60, 30, 14, 7, 3, 1)
REMINDER_CHANNELS: Final = ("telegram", "push", "email")
DEFAULT_QUIET_FROM: Final = dt.time(22, 0)
DEFAULT_QUIET_TO: Final = dt.time(8, 0)
REJECT_REASON_CODES: Final = ("illegible", "wrong_document", "expired", "other")
MILESTONE_KINDS: Final = (
    "application", "aid", "test_send", "rec", "docs", "decision", "deposit", "fee",
)  # fmt: skip
LIVE_ENTRY_STATUSES: Final = frozenset({"considering", "applying"})

AttachmentStatus = Literal["attached", "superseded", "detached"]
ChecklistStatus = Literal["todo", "in_progress", "done", "n_a", "confirm_with_uni"]
DeadlineStatus = Literal["confirmed", "predicted", "unknown", "confirm_with_uni"]


@dataclass(slots=True)
class DocumentRecord:
    """A stored document row."""

    id: UUID
    student_id: UUID
    kind: DocumentKind
    visibility: DocumentVisibility
    uploaded_by: UUID
    owner_kind: Literal["student", "institution"] = "student"
    current_version: int = 0
    review_status: ReviewStatus = "none"
    reject_reason_code: str | None = None
    reject_note: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    lock_version: int = 0


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    """One uploaded file of a document."""

    document_id: UUID
    version: int
    file_id: UUID
    scan_status: ScanStatus
    uploaded_by: UUID
    uploaded_at: dt.datetime | None = None


@dataclass(slots=True)
class AttachmentRecord:
    """A document version attached to one list entry."""

    id: UUID
    document_id: UUID
    document_version: int
    list_entry_id: UUID
    attached_by: UUID
    status: AttachmentStatus = "attached"
    attached_at: dt.datetime | None = None


@dataclass(slots=True)
class ChecklistItem:
    """A checklist line of a student or one list entry."""

    id: UUID
    student_id: UUID
    template_key: str
    title_key: str
    list_entry_id: UUID | None = None
    owner: str = "student"
    status: ChecklistStatus = "todo"
    due_utc: dt.datetime | None = None
    document_id: UUID | None = None
    source_url: str | None = None
    rule_version: int = 1
    lock_version: int = 0


@dataclass(slots=True)
class Deadline:
    """A versioned deadline of an institution; an edit adds a version."""

    id: UUID
    institution_id: UUID
    cycle: int
    round: str
    program_id: UUID | None = None
    precision: Literal["date_only", "instant"] = "date_only"
    source_text: str | None = None
    source_tz: str | None = None
    local_date: dt.date | None = None
    cutoff_time: dt.time | None = None
    instant_utc: dt.datetime | None = None
    binding: bool = False
    applies_to: str | None = None
    status: DeadlineStatus = "unknown"
    source_id: UUID | None = None
    version: int = 1
    superseded_by: UUID | None = None


@dataclass(slots=True)
class Milestone:
    """A dated step of a list entry, tied to a deadline version."""

    id: UUID
    list_entry_id: UUID
    kind: str
    due_utc: dt.datetime | None = None
    deadline_id: UUID | None = None
    deadline_version: int | None = None
    predicted: bool = False


@dataclass(slots=True)
class ReminderPrefs:
    """Which reminders a student gets, and when they stay quiet."""

    student_id: UUID
    offsets_days: tuple[int, ...] = REMINDER_OFFSETS
    channels: tuple[str, ...] = REMINDER_CHANNELS
    quiet_from: dt.time = DEFAULT_QUIET_FROM
    quiet_to: dt.time = DEFAULT_QUIET_TO
    lock_version: int = 0


@dataclass(slots=True)
class ReminderRecord:
    """A scheduled reminder of one milestone."""

    id: UUID
    student_id: UUID
    milestone_id: UUID
    schedule_version: int
    offset_days: int
    dedupe_key: str
    scheduled_at: dt.datetime
    sent_at: dt.datetime | None = None
    failed_at: dt.datetime | None = None
    superseded_at: dt.datetime | None = None


@dataclass(slots=True)
class DueMilestone:
    """A live milestone with its student, for the reminder job."""

    milestone: Milestone
    student_id: UUID
    institution_id: UUID


@dataclass(slots=True)
class Transcript:
    """A request to the registrar for a transcript; one open per student."""

    id: UUID
    student_id: UUID
    destination_note: str = ""
    status: TranscriptStatus = "requested"
    requested_at: dt.datetime | None = None
    ready_at: dt.datetime | None = None
    ready_by: UUID | None = None
    undo_until: dt.datetime | None = None
    pickup_location_snapshot: str | None = None
    cancelled_by: UUID | None = None
    cancelled_at: dt.datetime | None = None
    last_reminded_at: dt.datetime | None = None
    document_id: UUID | None = None
    lock_version: int = 0

    def move(self, target: TranscriptStatus) -> None:
        """Change status along the allowed transitions."""
        check_transition(TRANSCRIPT_TRANSITIONS, self.status, target)
        self.status = target

    def ready_key(self) -> str:
        """Return the dedupe key of the pending 'ready' notification."""
        return f"transcript:{self.id}:ready:{self.lock_version}"


@dataclass(slots=True)
class OfficerSettings:
    """A transcript officer's own pickup location per locale."""

    user_id: UUID
    pickup_location: dict[str, str] = field(default_factory=dict)
    lock_version: int = 0


def pick_text(texts: dict[str, str] | None, locale: str) -> str | None:
    """Return the text in the locale, else any non-empty one (ru, uz, en)."""
    if not texts:
        return None
    for key in (locale, "ru", "uz", "en"):
        if texts.get(key):
            return texts[key]
    return None


def reminder_key(milestone_id: UUID, deadline_version: int, offset: int) -> str:
    """Return the dedupe key of one reminder."""
    return f"reminder:{milestone_id}:{deadline_version}:{offset}"


def shift_out_of_quiet(
    when: dt.datetime, quiet_from: dt.time, quiet_to: dt.time
) -> dt.datetime:
    """Move a send time inside the quiet hours (Tashkent) to their end."""
    local = when.astimezone(TASHKENT)
    t = local.timetz().replace(tzinfo=None)
    if quiet_from == quiet_to:
        return when
    if quiet_from < quiet_to:
        inside = quiet_from <= t < quiet_to
        day_shift = 0
    else:
        inside = t >= quiet_from or t < quiet_to
        day_shift = 1 if t >= quiet_from else 0
    if not inside:
        return when
    end = dt.datetime.combine(local.date(), quiet_to, tzinfo=TASHKENT)
    return (end + dt.timedelta(days=day_shift)).astimezone(dt.UTC)


def confirmed_instant(deadline: Deadline) -> dt.datetime | None:
    """Return the UTC instant of a deadline whose time is certain, else None.

    A date-only deadline counts only when its zone and cutoff are known; a
    predicted or unknown one never yields an instant to alarm on.
    """
    if deadline.status != "confirmed":
        return None
    if deadline.precision == "instant":
        return deadline.instant_utc
    if deadline.local_date and deadline.cutoff_time and deadline.source_tz:
        local = dt.datetime.combine(
            deadline.local_date, deadline.cutoff_time, ZoneInfo(deadline.source_tz)
        )
        return local.astimezone(dt.UTC)
    return None
