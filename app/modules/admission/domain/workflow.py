"""Applications, documents, transcripts, comments, views.

Tech plan §3.2–§3.5.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.transitions import check_transition

Round = Literal["RD", "EA", "ED", "ED2", "REA", "SCEA", "rolling", "other"]
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
