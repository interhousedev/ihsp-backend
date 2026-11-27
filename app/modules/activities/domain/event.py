"""Events, RSVP, waitlist and check-in."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from app.modules.activities.domain.errors import Conflict, Denied, Invalid

__all__ = [
    "CHECK_IN_CLOSES_AFTER",
    "CHECK_IN_OPENS_BEFORE",
    "CheckInWindowError",
    "Event",
    "EventInvalidError",
    "EventStateError",
    "EventStatus",
    "NotMemberError",
    "Rsvp",
    "RsvpPolicy",
    "check_in",
    "check_in_window",
    "promote_waitlist",
]

CHECK_IN_OPENS_BEFORE = timedelta(hours=1)
CHECK_IN_CLOSES_AFTER = timedelta(hours=1)
CHECK_IN_METHODS = ("qr", "manual")


class EventStatus(StrEnum):
    """Event lifecycle."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    DONE = "done"


class RsvpPolicy(StrEnum):
    """Who may RSVP and how."""

    OPEN = "open"
    MEMBERS = "members"
    APPROVAL = "approval"


class EventInvalidError(Invalid):
    """An event field is invalid."""


class EventStateError(Conflict):
    """The event's state does not allow this."""


class NotMemberError(Denied):
    """The event is for members only."""


class CheckInWindowError(Conflict):
    """Check-in is outside its time window."""


@dataclass(slots=True)
class Event:
    """A club event."""

    id: UUID
    club_id: UUID
    title: Any
    starts_at: datetime
    ends_at: datetime
    capacity: int | None
    rsvp_policy: RsvpPolicy
    status: EventStatus
    description: Any = None
    location: str | None = None
    course_id: UUID | None = None
    opportunity_id: UUID | None = None
    schedule_revision: int = 0
    rating_requested_at: datetime | None = None
    created_by: UUID | None = None

    def validate(self) -> None:
        """Times are timezone-aware and the end follows the start."""
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise EventInvalidError(params={"field": "starts_at"})
        if self.ends_at <= self.starts_at:
            raise EventInvalidError(params={"field": "ends_at"})
        if self.capacity is not None and self.capacity < 1:
            raise EventInvalidError(params={"field": "capacity"})

    def schedule(self) -> None:
        """Publish a draft."""
        if self.status != EventStatus.DRAFT:
            raise EventStateError(params={"status": str(self.status)})
        self.status = EventStatus.SCHEDULED

    def cancel(self) -> None:
        """Cancel a draft or scheduled event."""
        if self.status not in (EventStatus.DRAFT, EventStatus.SCHEDULED):
            raise EventStateError(params={"status": str(self.status)})
        self.status = EventStatus.CANCELLED

    def mark_done(self) -> None:
        """Close a scheduled event."""
        if self.status != EventStatus.SCHEDULED:
            raise EventStateError(params={"status": str(self.status)})
        self.status = EventStatus.DONE

    def reschedule(self, starts_at: datetime, ends_at: datetime) -> bool:
        """Move the event; True when the time changed (the revision then grows)."""
        if self.status not in (EventStatus.DRAFT, EventStatus.SCHEDULED):
            raise EventStateError(params={"status": str(self.status)})
        probe = Event(
            self.id,
            self.club_id,
            self.title,
            starts_at,
            ends_at,
            self.capacity,
            self.rsvp_policy,
            self.status,
        )
        probe.validate()
        if (starts_at, ends_at) == (self.starts_at, self.ends_at):
            return False
        self.starts_at, self.ends_at = starts_at, ends_at
        self.schedule_revision += 1
        return True


def check_in_window(event: Event) -> tuple[datetime, datetime]:
    """From one hour before the start to one hour after the end."""
    return (
        event.starts_at - CHECK_IN_OPENS_BEFORE,
        event.ends_at + CHECK_IN_CLOSES_AFTER,
    )


@dataclass(slots=True)
class Rsvp:
    """A person's place at an event."""

    event_id: UUID
    user_id: UUID
    status: str
    created_at: datetime
    checked_in_at: datetime | None = None
    check_in_method: str | None = None
    event_role: str | None = None
    id: UUID = field(default_factory=uuid4)

    @classmethod
    def request(
        cls,
        event: Event,
        user_id: UUID,
        going_count: int,
        is_member: bool,
        now: datetime | None = None,
    ) -> "Rsvp":
        """Going, waitlisted or waiting for approval, by the event's policy."""
        if event.status != EventStatus.SCHEDULED:
            raise EventStateError(params={"status": str(event.status)})
        if event.rsvp_policy == RsvpPolicy.MEMBERS and not is_member:
            raise NotMemberError()
        if event.rsvp_policy == RsvpPolicy.APPROVAL:
            status = "requested"
        elif event.capacity is None or going_count < event.capacity:
            status = "going"
        else:
            status = "waitlist"
        return cls(event.id, user_id, status, now or datetime.now(UTC))


def promote_waitlist(rsvps: list[Rsvp]) -> Rsvp | None:
    """Move the oldest waitlisted person to going."""
    waiting = [r for r in rsvps if r.status == "waitlist"]
    if not waiting:
        return None
    first = min(waiting, key=lambda r: r.created_at)
    first.status = "going"
    return first


def check_in(rsvp: Rsvp, method: str, now: datetime, *, event: Event) -> None:
    """Mark attendance inside the window; only for a going RSVP."""
    if method not in CHECK_IN_METHODS:
        raise ValueError(f"unknown check-in method: {method}")
    if event.status != EventStatus.SCHEDULED or rsvp.status != "going":
        raise EventStateError(params={"status": str(event.status)})
    opens, closes = check_in_window(event)
    if not opens <= now <= closes:
        raise CheckInWindowError()
    rsvp.checked_in_at, rsvp.check_in_method = now, method
