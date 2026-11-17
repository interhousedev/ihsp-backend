"""Consultations: a student asks a counselor or a mentor for a conversation.

The request names a topic, the item it is about, a few preferred times and a
format. Staff accept it, propose another time, decline it, or complete it with
notes. The student confirms or rejects a proposed time, or cancels.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    CharLimitError,
    InvalidTransitionError,
    ItemLimitError,
)
from app.modules.admission.domain.transitions import check_transition

WithKind = Literal["counselor", "mentor"]
LinkedKind = Literal["project", "essay", "activity", "application", "other"]
ConsultFormat = Literal["online", "offline"]
ConsultStatus = Literal[
    "requested", "proposed", "accepted", "declined", "completed", "cancelled"
]

WITH_KINDS: Final = ("counselor", "mentor")
LINKED_KINDS: Final = ("project", "essay", "activity", "application", "other")
FORMATS: Final = ("online", "offline")
STATUSES: Final = (
    "requested",
    "proposed",
    "accepted",
    "declined",
    "completed",
    "cancelled",
)
ACTIVE: Final = ("requested", "proposed", "accepted")
MAX_ACTIVE: Final = 3
MAX_TIMES: Final = 5
TOPIC_MAX: Final = 200
DETAILS_MAX: Final = 1000
LOCATION_MAX: Final = 200
NOTES_MAX: Final = 2000

CONSULT_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "requested": frozenset({"proposed", "accepted", "declined", "cancelled"}),
    "proposed": frozenset({"accepted", "requested", "declined", "cancelled"}),
    "accepted": frozenset({"completed", "proposed", "cancelled"}),
    "declined": frozenset(),
    "completed": frozenset(),
    "cancelled": frozenset(),
}


def _limit(field_name: str, value: str, limit: int) -> None:
    if len(value) > limit:
        raise CharLimitError(params={"field": field_name, "limit": limit})


@dataclass(slots=True)
class Consultation:
    """One consultation request with its scheduling state."""

    id: UUID
    student_id: UUID
    with_kind: WithKind
    topic: str
    linked_kind: LinkedKind = "other"
    linked_id: UUID | None = None
    details: str = ""
    preferred_times: tuple[dt.datetime, ...] = ()
    format: ConsultFormat = "online"
    status: ConsultStatus = "requested"
    staff_id: UUID | None = None
    scheduled_at: dt.datetime | None = None
    location: str = ""
    staff_notes: str = ""
    decline_reason: str = ""
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    lock_version: int = 0

    def move(self, target: ConsultStatus) -> None:
        """Change status along the allowed transitions."""
        check_transition(CONSULT_TRANSITIONS, self.status, target)
        self.status = target

    def propose(
        self,
        staff_id: UUID,
        at: dt.datetime,
        location: str,
        now: dt.datetime,
    ) -> None:
        """Staff offer a concrete time; the student then confirms or rejects."""
        _check_slot(at, location, now)
        self.move("proposed")
        self.staff_id = staff_id
        self.scheduled_at = at
        self.location = location

    def accept(
        self,
        staff_id: UUID,
        at: dt.datetime | None,
        location: str,
        now: dt.datetime,
    ) -> None:
        """Staff take the request; the first preferred time is the default."""
        slot = at or (self.preferred_times[0] if self.preferred_times else None)
        if slot is None:
            raise AdmissionConflictError(params={"reason": "time_required"})
        _check_slot(slot, location, now)
        self.move("accepted")
        self.staff_id = staff_id
        self.scheduled_at = slot
        self.location = location

    def confirm(self) -> None:
        """The student agrees to the proposed time."""
        if self.status != "proposed":
            raise InvalidTransitionError(
                params={"status": self.status, "target": "accepted"}
            )
        self.move("accepted")

    def reject_proposal(self) -> None:
        """The student turns the proposed time down; the request is open again."""
        self.move("requested")
        self.staff_id = None
        self.scheduled_at = None
        self.location = ""

    def decline(self, staff_id: UUID, reason: str) -> None:
        """Staff cannot take the request."""
        _limit("reason", reason, DETAILS_MAX)
        self.move("declined")
        self.staff_id = staff_id
        self.decline_reason = reason

    def complete(self, notes: str, now: dt.datetime) -> None:
        """Staff close the consultation with notes shared with the student."""
        _limit("notes", notes, NOTES_MAX)
        self.move("completed")
        self.staff_notes = notes
        self.completed_at = now

    def cancel(self) -> None:
        """Either side withdraws the consultation."""
        self.move("cancelled")


def _check_slot(at: dt.datetime, location: str, now: dt.datetime) -> None:
    if at.tzinfo is None:
        raise AdmissionConflictError(params={"reason": "naive_time"})
    if at <= now:
        raise AdmissionConflictError(params={"reason": "time_in_past"})
    _limit("location", location, LOCATION_MAX)


def check_new(
    topic: str,
    details: str,
    times: tuple[dt.datetime, ...],
    active_count: int,
    now: dt.datetime,
) -> None:
    """Validate a new request; raises a domain error."""
    if not topic.strip():
        raise CharLimitError(params={"field": "topic", "limit": TOPIC_MAX})
    _limit("topic", topic, TOPIC_MAX)
    _limit("details", details, DETAILS_MAX)
    if len(times) > MAX_TIMES:
        raise ItemLimitError(params={"kind": "preferred_times", "limit": MAX_TIMES})
    if any(t.tzinfo is None or t <= now for t in times):
        raise AdmissionConflictError(params={"reason": "time_in_past"})
    if active_count >= MAX_ACTIVE:
        raise ItemLimitError(params={"kind": "consultation", "limit": MAX_ACTIVE})
