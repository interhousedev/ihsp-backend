"""Help requests, guest links, applications, documents, transcripts, comments, views.

Tech plan §3.2–§3.5.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import GuestLinkLimitError
from app.modules.admission.domain.transitions import check_transition

HelpKind = Literal["website", "design", "proof", "other"]
HelpStatus = Literal[
    "open", "assigned", "accepted", "declined", "delivered", "closed", "cancelled",
    "expired",
]  # fmt: skip
HELP_TRANSITIONS: Final = {
    "open": frozenset({"assigned", "cancelled", "expired"}),
    "assigned": frozenset({"accepted", "declined", "cancelled", "expired"}),
    "accepted": frozenset({"delivered", "cancelled", "expired"}),
    "declined": frozenset({"assigned", "cancelled"}),
    "delivered": frozenset({"closed", "accepted"}),
    "closed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}
HELP_DEFAULT_DAYS: Final = 30
HELP_BRIEF_MAX: Final = 1000
HELP_RESPONSE_MAX: Final = 2000


@dataclass(slots=True)
class HelpRequest:
    """A student's request for help with an item, or a general one."""

    id: UUID
    student_id: UUID
    kind: HelpKind
    brief: str
    expires_at: datetime
    item_id: UUID | None = None
    helper_user_id: UUID | None = None
    status: HelpStatus = "open"
    lock_version: int = 0

    def move(self, target: HelpStatus) -> None:
        """Change status along the allowed transitions."""
        check_transition(HELP_TRANSITIONS, self.status, target)
        self.status = target


GuestScope = Literal["activities:read", "help:respond"]
GUEST_DEFAULT_DAYS: Final = 14
GUEST_MAX_DAYS: Final = 60
GUEST_DEFAULT_SESSIONS: Final = 5
GUEST_MAX_SESSIONS: Final = 20
GUEST_SESSION_HOURS: Final = 2


@dataclass(frozen=True, slots=True)
class GuestLink:
    """A guest link; only the SHA-256 of its token is stored."""

    id: UUID
    student_id: UUID
    help_request_id: UUID
    scope: tuple[GuestScope, ...]
    token_hash: str
    token_prefix: str
    expires_at: datetime
    max_sessions: int
    sessions_used: int = 0
    revoked_at: datetime | None = None

    def usable(self, now: datetime) -> bool:
        """Return whether a new guest session may open."""
        return (
            self.revoked_at is None
            and now < self.expires_at
            and self.sessions_used < self.max_sessions
        )


def guest_link_terms(
    now: datetime, days: int | None, sessions: int | None
) -> tuple[datetime, int]:
    """Return (expires_at, max_sessions) after defaults and caps."""
    d = GUEST_DEFAULT_DAYS if days is None else days
    s = GUEST_DEFAULT_SESSIONS if sessions is None else sessions
    if not 1 <= d <= GUEST_MAX_DAYS or not 1 <= s <= GUEST_MAX_SESSIONS:
        raise GuestLinkLimitError(
            params={"max_days": GUEST_MAX_DAYS, "max_sessions": GUEST_MAX_SESSIONS}
        )
    return now + timedelta(days=d), s


Round = Literal["RD", "EA", "ED", "ED2", "REA", "rolling", "other"]
ListStatus = Literal[
    "considering", "applying", "submitted", "admitted", "waitlisted", "deferred",
    "rejected", "enrolled", "withdrawn",
]  # fmt: skip
_DECIDED: Final = frozenset({"admitted", "waitlisted", "deferred", "rejected"})
LIST_TRANSITIONS: Final = {
    "considering": frozenset({"applying", "withdrawn"}),
    "applying": frozenset({"submitted", "considering", "withdrawn"}),
    "submitted": _DECIDED | {"withdrawn"},
    "deferred": frozenset({"admitted", "waitlisted", "rejected", "withdrawn"}),
    "waitlisted": frozenset({"admitted", "rejected", "withdrawn"}),
    "admitted": frozenset({"enrolled", "withdrawn"}),
    "rejected": frozenset(),
    "enrolled": frozenset(),
    "withdrawn": frozenset({"considering"}),
}
Label = Literal["reach", "target", "safety"]
AffordabilityStatus = Literal["feasible", "gap", "unknown", "signed_off"]


@dataclass(slots=True)
class ListEntry:
    """One institution on the student's application list."""

    id: UUID
    student_id: UUID
    institution_id: UUID
    round: Round = "RD"
    status: ListStatus = "considering"
    campus_id: UUID | None = None
    program_id: UUID | None = None
    label_override: Label | None = None
    affordability_status: AffordabilityStatus = "unknown"
    lock_version: int = 0

    def move(self, target: ListStatus) -> None:
        """Change status along the allowed transitions."""
        check_transition(LIST_TRANSITIONS, self.status, target)
        self.status = target


DocumentKind = Literal[
    "transcript", "school_report", "rec", "certificate", "passport", "translation",
    "test_report", "bank", "other",
]  # fmt: skip
# `unscanned` while AV is deferred (addendum); the rest once scanning exists.
ScanStatus = Literal["unscanned", "pending_scan", "clean", "infected", "failed"]
DocumentVisibility = Literal["student", "confidential"]
CONFIDENTIAL_KINDS: Final = frozenset({"transcript", "school_report", "rec"})
ReviewStatus = Literal["none", "accepted", "rejected"]


@dataclass(frozen=True, slots=True)
class Document:
    """A document; confidential ones need `documents:confidential` or ownership."""

    id: UUID
    student_id: UUID
    kind: DocumentKind
    visibility: DocumentVisibility
    owner_kind: Literal["student", "institution"] = "student"
    current_version: int = 1
    review_status: ReviewStatus = "none"


def default_visibility(kind: DocumentKind) -> DocumentVisibility:
    """Return the visibility a new document of this kind gets."""
    return "confidential" if kind in CONFIDENTIAL_KINDS else "student"


TranscriptStatus = Literal["requested", "ready", "cancelled"]
TRANSCRIPT_TRANSITIONS: Final = {
    "requested": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"requested"}),  # officer undo within `undo_until`
    "cancelled": frozenset(),
}
TRANSCRIPT_UNDO_SECONDS: Final = 120


@dataclass(slots=True)
class TranscriptRequest:
    """A request for a transcript from the registrar; one open per student."""

    id: UUID
    student_id: UUID
    destination_note: str = ""
    status: TranscriptStatus = "requested"
    undo_until: datetime | None = None
    pickup_location_snapshot: str | None = None
    lock_version: int = 0

    def move(self, target: TranscriptStatus) -> None:
        """Change status along the allowed transitions."""
        check_transition(TRANSCRIPT_TRANSITIONS, self.status, target)
        self.status = target


CommentTarget = Literal[
    "profile", "item", "list_entry", "essay", "words", "help_request"
]
CommentVisibility = Literal["student_and_staff", "staff_only"]
COMMENT_MAX: Final = 2000


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment on a student's object."""

    id: UUID
    student_id: UUID
    target_kind: CommentTarget
    target_id: UUID
    author_id: UUID
    body: str
    visibility: CommentVisibility = "student_and_staff"


SAVED_VIEW_NAME_MAX: Final = 60
SAVED_VIEWS_MAX: Final = 20
SAVED_VIEW_FILTER_KEYS: Final = frozenset(
    {"stage", "cohort", "status", "label", "deadline_within_days", "missing_docs"}
)
