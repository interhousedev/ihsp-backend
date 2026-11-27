"""Events, RSVPs, ratings, announcements and the planner board."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.activities.deps import (
    ActorDep,
    ContainerDep,
    IdOut,
    ItemsOut,
    PlannerBoardOut,
    RatingsSummaryOut,
    TokenOut,
    items,
)
from app.modules.activities.domain.announcement import Announcement
from app.modules.activities.domain.event import Event, Rsvp
from app.modules.activities.domain.planner import PlannerItem, PlannerStatus
from app.modules.activities.domain.rating import Rating

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/activities", tags=["activities"])


class EventIn(BaseModel):
    """A new event (a draft until published)."""

    title: Any
    starts_at: datetime
    ends_at: datetime
    capacity: int | None = Field(default=None, ge=1)
    rsvp_policy: str = "open"
    description: Any = None
    location: str | None = Field(default=None, max_length=300)
    course_id: UUID | None = None
    opportunity_id: UUID | None = None


class RescheduleIn(BaseModel):
    """New times."""

    starts_at: datetime
    ends_at: datetime


class CheckInIn(BaseModel):
    """Manual check-in."""

    user_id: UUID
    method: str = "manual"


class QrCheckInIn(BaseModel):
    """Check-in by the event's QR token."""

    token: str


class RoleIn(BaseModel):
    """An event role of an attendee."""

    role: str = Field(max_length=60)


class RatingIn(BaseModel):
    """A 1..5 rating."""

    score: int = Field(ge=1, le=5)
    aspects: dict[str, int] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)
    anonymous_to_club: bool = False


class RevealIn(BaseModel):
    """Why an author is unmasked."""

    reason: str = Field(min_length=1, max_length=500)


class AnnouncementIn(BaseModel):
    """A message to a part of the club."""

    text: str = Field(min_length=1, max_length=4000)
    audience: str = "members"
    scheduled_at: datetime | None = None


class PlannerIn(BaseModel):
    """A planner card."""

    title: str = Field(min_length=1, max_length=200)
    kind: str = "task"
    body: str = Field(default="", max_length=4000)
    assignee_id: UUID | None = None
    due_at: datetime | None = None


class MoveIn(BaseModel):
    """Planner column."""

    status: PlannerStatus


@router.post("/clubs/{club_id}/events", status_code=status.HTTP_201_CREATED)
async def create_event(
    club_id: UUID, body: EventIn, container: ContainerDep, actor: ActorDep
) -> IdOut:
    """Create an event draft."""
    extra = body.model_dump(
        exclude={"title", "starts_at", "ends_at", "capacity", "rsvp_policy"}
    )
    event = await container.activities.events.create(
        actor,
        club_id,
        body.title,
        body.starts_at,
        body.ends_at,
        body.capacity,
        body.rsvp_policy,
        **extra,
    )
    return IdOut(id=str(event.id))


@router.post("/events/{event_id}:publish")
async def publish_event(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> Event:
    """Open the event."""
    return await container.activities.events.publish(actor, event_id)


@router.post("/events/{event_id}:cancel")
async def cancel_event(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> Event:
    """Cancel the event."""
    return await container.activities.events.cancel(actor, event_id)


@router.post("/events/{event_id}:finish")
async def finish_event(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> Event:
    """Close the event."""
    return await container.activities.events.finish(actor, event_id)


@router.post("/events/{event_id}:reschedule")
async def reschedule_event(
    event_id: UUID, body: RescheduleIn, container: ContainerDep, actor: ActorDep
) -> Event:
    """Move the event."""
    return await container.activities.events.reschedule(
        actor, event_id, body.starts_at, body.ends_at
    )


@router.get("/clubs/{club_id}/events")
async def list_club_events(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[Event]:
    """Events of a club."""
    return items(await container.activities.events.list_for_club(actor, club_id))


@router.get("/events")
async def events_feed(container: ContainerDep, actor: ActorDep) -> ItemsOut[Event]:
    """Upcoming events of my clubs and public clubs."""
    return items(await container.activities.events.feed(actor))


@router.get("/events/{event_id}")
async def get_event(event_id: UUID, container: ContainerDep, actor: ActorDep) -> Event:
    """One event."""
    return await container.activities.events.get(actor, event_id)


@router.get("/events/{event_id}/rsvp")
async def my_rsvp(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> Rsvp | None:
    """My place at the event, or null."""
    return await container.activities.events.my_rsvp(actor, event_id)


@router.put("/events/{event_id}/rsvp")
async def rsvp(event_id: UUID, container: ContainerDep, actor: ActorDep) -> Rsvp:
    """Take a place (going, waitlist or requested)."""
    return await container.activities.events.rsvp(actor, event_id)


@router.delete("/events/{event_id}/rsvp", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_rsvp(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> Response:
    """Give the place back."""
    await container.activities.events.cancel_rsvp(actor, event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/events/{event_id}/rsvps")
async def list_rsvps(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[Rsvp]:
    """Who signed up."""
    return items(await container.activities.events.list_rsvps(actor, event_id))


@router.post("/events/{event_id}/check-in")
async def check_in(
    event_id: UUID, body: CheckInIn, container: ContainerDep, actor: ActorDep
) -> Rsvp:
    """Mark an attendee present."""
    return await container.activities.events.check_in(
        actor, event_id, body.user_id, body.method
    )


@router.get("/events/{event_id}/qr")
async def event_qr(
    event_id: UUID, container: ContainerDep, actor: ActorDep
) -> TokenOut:
    """The token behind the event's check-in QR code."""
    return TokenOut(token=await container.activities.events.qr_token(actor, event_id))


@router.post("/check-in/qr")
async def check_in_qr(
    body: QrCheckInIn, container: ContainerDep, actor: ActorDep
) -> Rsvp:
    """Check in by scanning the QR code."""
    return await container.activities.events.check_in_qr(actor, body.token)


@router.put("/events/{event_id}/rsvps/{user_id}/role")
async def assign_role(
    event_id: UUID,
    user_id: UUID,
    body: RoleIn,
    container: ContainerDep,
    actor: ActorDep,
) -> Rsvp:
    """Give an attendee a role."""
    return await container.activities.events.assign_role(
        actor, event_id, user_id, body.role
    )


@router.post("/events/{event_id}/ratings", status_code=status.HTTP_201_CREATED)
async def rate_event(
    event_id: UUID, body: RatingIn, container: ContainerDep, actor: ActorDep
) -> Rating:
    """Rate an event you attended."""
    return await container.activities.ratings.rate_event(
        actor, event_id, **body.model_dump()
    )


@router.post("/clubs/{club_id}/ratings", status_code=status.HTTP_201_CREATED)
async def rate_club(
    club_id: UUID, body: RatingIn, container: ContainerDep, actor: ActorDep
) -> Rating:
    """Rate a club you belong to."""
    return await container.activities.ratings.rate_club(
        actor, club_id, **body.model_dump()
    )


@router.get("/clubs/{club_id}/ratings/summary")
async def ratings_summary(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> RatingsSummaryOut:
    """Aggregates for organizers."""
    return RatingsSummaryOut.model_validate(
        await container.activities.ratings.summary(actor, club_id)
    )


@router.post("/ratings/{rating_id}:reveal-author")
async def reveal_author(
    rating_id: UUID, body: RevealIn, container: ContainerDep, actor: ActorDep
) -> Rating:
    """Administrators unmask an author (audited)."""
    return await container.activities.ratings.reveal_author(
        actor, rating_id, body.reason
    )


@router.post("/clubs/{club_id}/announcements", status_code=status.HTTP_201_CREATED)
async def send_announcement(
    club_id: UUID, body: AnnouncementIn, container: ContainerDep, actor: ActorDep
) -> Announcement:
    """Send or schedule an announcement."""
    return await container.activities.announcements.send(
        actor, club_id, body.text, body.audience, body.scheduled_at
    )


@router.get("/clubs/{club_id}/announcements")
async def list_announcements(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> ItemsOut[Announcement]:
    """Announcements of a club."""
    return items(await container.activities.announcements.list(actor, club_id))


@router.post("/announcements/{announcement_id}:cancel")
async def cancel_announcement(
    announcement_id: UUID, container: ContainerDep, actor: ActorDep
) -> Announcement:
    """Cancel a scheduled announcement."""
    return await container.activities.announcements.cancel(actor, announcement_id)


@router.post("/clubs/{club_id}/planner", status_code=status.HTTP_201_CREATED)
async def add_card(
    club_id: UUID, body: PlannerIn, container: ContainerDep, actor: ActorDep
) -> PlannerItem:
    """Add a task or idea."""
    return await container.activities.planner.add(actor, club_id, **body.model_dump())


@router.get("/clubs/{club_id}/planner")
async def board(
    club_id: UUID, container: ContainerDep, actor: ActorDep
) -> PlannerBoardOut:
    """The planner board."""
    return PlannerBoardOut.model_validate(
        await container.activities.planner.board(actor, club_id)
    )


@router.post("/planner/{item_id}:move")
async def move_card(
    item_id: UUID, body: MoveIn, container: ContainerDep, actor: ActorDep
) -> PlannerItem:
    """Move a card to another column."""
    return await container.activities.planner.move(actor, item_id, body.status)
