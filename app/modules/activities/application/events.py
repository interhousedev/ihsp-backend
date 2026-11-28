"""Events: lifecycle, RSVP, reminders, check-in, QR tokens, rating requests."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.activities.application.common import (
    active_member,
    award,
    load_club,
    load_event,
    note,
    organizer_ids,
    permissions,
    require,
)
from app.modules.activities.application.media import MediaService
from app.modules.activities.domain.access import Permission
from app.modules.activities.domain.checkin_token import (
    InvalidCheckInTokenError,
    issue_token,
    peek_event_id,
    verify_token,
)
from app.modules.activities.domain.club import Club, ClubStateError, ClubStatus
from app.modules.activities.domain.course_link import CourseLinkDeniedError
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.event import (
    Event,
    EventStateError,
    EventStatus,
    Rsvp,
    RsvpPolicy,
    check_in,
    promote_waitlist,
)
from app.modules.activities.domain.media import Media
from app.modules.activities.domain.reminders import (
    plan_reminders,
    rating_request_time,
    reminder_prefix,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.notifications import NotificationType

from uuid_utils.compat import uuid7

_LIVE = ("going", "waitlist", "requested")


class EventService:
    """Club events and everything attached to them."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def create(
        self,
        actor: Actor,
        club_id: UUID,
        title: Any,
        starts_at: datetime,
        ends_at: datetime,
        capacity: int | None = None,
        rsvp_policy: str = "open",
        **extra: Any,
    ) -> Event:
        """A draft event; organizers only."""
        p = self._p
        await require(p, actor, club_id, Permission.EDIT_EVENTS)
        club = await load_club(p, club_id)
        if club.status != ClubStatus.ACTIVE:
            raise ClubStateError(params={"status": str(club.status)})
        course_id = extra.get("course_id")
        if course_id is not None and not any(
            link.status == "active"
            for link in await p.links.list_pair(club_id, course_id)
        ):
            raise CourseLinkDeniedError()
        event = Event(
            uuid7(),
            club_id,
            title,
            starts_at,
            ends_at,
            capacity,
            RsvpPolicy(rsvp_policy),
            EventStatus.DRAFT,
            description=extra.get("description"),
            location=extra.get("location"),
            course_id=course_id,
            opportunity_id=extra.get("opportunity_id"),
            created_by=actor.user_id,
        )
        event.validate()
        await p.events.add(event)
        return event

    async def _visible_club(self, actor: Actor, club_id: UUID) -> tuple[Club, bool]:
        """The club and whether the actor may manage its events; 404 if hidden."""
        club = await load_club(self._p, club_id)
        perms = await permissions(self._p, actor, club_id)
        public = club.status == ClubStatus.ACTIVE and club.visibility_public
        if not public and not perms:
            raise ActivitiesNotFoundError()
        return club, Permission.EDIT_EVENTS in perms

    async def list_for_club(self, actor: Actor, club_id: UUID) -> list[Event]:
        """Events of a club; drafts only for its organizers."""
        _, manages = await self._visible_club(actor, club_id)
        events = await self._p.events.list_for_club(club_id)
        return [e for e in events if manages or e.status != EventStatus.DRAFT]

    async def get(self, actor: Actor, event_id: UUID) -> Event:
        """One event; drafts only for organizers."""
        event = await load_event(self._p, event_id)
        _, manages = await self._visible_club(actor, event.club_id)
        if event.status == EventStatus.DRAFT and not manages:
            raise ActivitiesNotFoundError()
        return event

    async def my_rsvp(self, actor: Actor, event_id: UUID) -> Rsvp | None:
        """The actor's own RSVP, if any."""
        event = await self.get(actor, event_id)
        return await self._p.events.get_rsvp(event.id, actor.user_id)

    async def feed(self, actor: Actor) -> list[Event]:
        """Upcoming scheduled events of the actor's clubs and public clubs."""
        p = self._p
        now = p.clock.now()
        memberships = await p.members.list_for_user(actor.user_id)
        mine = {m.club_id for m in memberships if m.is_active}
        shown = {
            c.id
            for c in await p.clubs.list_all()
            if c.status == ClubStatus.ACTIVE and c.visibility_public
        }
        out = [
            e
            for e in await p.events.list_all()
            if e.club_id in (mine | shown)
            and e.status == EventStatus.SCHEDULED
            and e.ends_at >= now
        ]
        return sorted(out, key=lambda e: e.starts_at)

    async def _managed(self, actor: Actor, event_id: UUID) -> Event:
        event = await load_event(self._p, event_id)
        await require(self._p, actor, event.club_id, Permission.EDIT_EVENTS)
        return event

    async def _participants(self, event: Event) -> list[UUID]:
        return [
            r.user_id
            for r in await self._p.events.list_rsvps(event.id)
            if r.status == "going"
        ]

    async def _plan(self, event: Event) -> None:
        p = self._p
        drafts = plan_reminders(
            event,
            await self._participants(event),
            await organizer_ids(p, event.club_id),
            p.clock.now(),
        )
        if drafts:
            await p.notifier.send(drafts)

    async def publish(self, actor: Actor, event_id: UUID) -> Event:
        """Open the event and schedule reminders."""
        event = await self._managed(actor, event_id)
        event.schedule()
        await self._p.events.save(event)
        await self._plan(event)
        return event

    async def update(
        self,
        actor: Actor,
        event_id: UUID,
        *,
        title: Any = None,
        description: Any = None,
        location: str | None = None,
        capacity: int | None = None,
        rsvp_policy: str | None = None,
    ) -> Event:
        """Edit the texts, capacity and RSVP policy (the time stays on reschedule)."""
        event = await self._managed(actor, event_id)
        if event.status not in (EventStatus.DRAFT, EventStatus.SCHEDULED):
            raise EventStateError(params={"status": str(event.status)})
        if title is not None:
            event.title = title
        if description is not None:
            event.description = description
        if location is not None:
            event.location = location
        if capacity is not None:
            event.capacity = capacity
        if rsvp_policy is not None:
            event.rsvp_policy = RsvpPolicy(rsvp_policy)
        event.validate()
        await self._p.events.save(event)
        return event

    async def set_cover(
        self, actor: Actor, event_id: UUID, media_id: UUID | None
    ) -> Event:
        """Use a staged ready photo as the cover; ``None`` removes it."""
        p = self._p
        event = await self._managed(actor, event_id)
        now = p.clock.now()
        new: Media | None = None
        if media_id is not None and media_id != event.cover_media_id:
            (new,) = await MediaService(p).stage_for(actor, event.club_id, [media_id])
            new.attach_as_cover(event.id)
            new.updated_at = now
        if media_id == event.cover_media_id:
            return event
        old = await p.media.get(event.cover_media_id) if event.cover_media_id else None
        if old is not None:
            old.soft_delete(now)
            old.updated_at = now
            await p.media.save(old)
        if new is not None:
            await p.media.save(new)
        event.cover_media_id = new.id if new else None
        await p.events.save(event)
        return event

    async def reschedule(
        self, actor: Actor, event_id: UUID, starts_at: datetime, ends_at: datetime
    ) -> Event:
        """Move the event: fresh reminders and a change notice."""
        p = self._p
        event = await self._managed(actor, event_id)
        if event.reschedule(starts_at, ends_at):
            await p.events.save(event)
            await p.notifier.cancel_scheduled(reminder_prefix(event.id))
            await self._plan(event)
            rsvps = await p.events.list_rsvps(event.id)
            await p.notifier.send(
                [
                    note(
                        r.user_id,
                        NotificationType.EVENT_CHANGED,
                        {
                            "event_id": str(event.id),
                            "club_id": str(event.club_id),
                            "starts_at": starts_at.isoformat(),
                        },
                        f"activities:event-changed:{event.id}:"
                        f"{event.schedule_revision}:{r.user_id}",
                    )
                    for r in rsvps
                    if r.status in _LIVE
                ]
            )
        return event

    async def cancel(self, actor: Actor, event_id: UUID) -> Event:
        """Cancel, drop pending reminders and tell the people."""
        p = self._p
        event = await self._managed(actor, event_id)
        event.cancel()
        await p.events.save(event)
        await p.notifier.cancel_scheduled(reminder_prefix(event.id))
        await p.notifier.send(
            [
                note(
                    r.user_id,
                    NotificationType.EVENT_CANCELLED,
                    {"event_id": str(event.id), "club_id": str(event.club_id)},
                    f"activities:event-cancelled:{event.id}:{r.user_id}",
                )
                for r in await p.events.list_rsvps(event.id)
                if r.status in _LIVE
            ]
        )
        return event

    async def finish(self, actor: Actor, event_id: UUID) -> Event:
        """Close the event."""
        event = await self._managed(actor, event_id)
        event.mark_done()
        await self._p.events.save(event)
        return event

    async def rsvp(self, actor: Actor, event_id: UUID) -> Rsvp:
        """Take a place; repeating returns the current one."""
        p = self._p
        event = await load_event(p, event_id)
        current = await p.events.get_rsvp(event_id, actor.user_id)
        if current is not None and current.status != "cancelled":
            return current
        going = sum(
            1 for r in await p.events.list_rsvps(event_id) if r.status == "going"
        )
        member = await active_member(p, event.club_id, actor.user_id) is not None
        rsvp = Rsvp.request(event, actor.user_id, going, member, p.clock.now())
        if current is not None:
            rsvp.id = current.id
        await p.events.save_rsvp(rsvp)
        if rsvp.status == "going":
            await self._plan(event)
        return rsvp

    async def cancel_rsvp(self, actor: Actor, event_id: UUID) -> None:
        """Give the place back; the waitlist moves up."""
        p = self._p
        event = await load_event(p, event_id)
        rsvp = await p.events.get_rsvp(event_id, actor.user_id)
        if rsvp is None or rsvp.status == "cancelled":
            raise ActivitiesNotFoundError()
        was_going = rsvp.status == "going"
        rsvp.status = "cancelled"
        await p.events.save_rsvp(rsvp)
        await p.notifier.cancel_scheduled(
            reminder_prefix(event_id), user_id=actor.user_id
        )
        if was_going:
            promoted = promote_waitlist(await p.events.list_rsvps(event_id))
            if promoted is not None:
                await p.events.save_rsvp(promoted)
                await self._plan(event)

    async def list_rsvps(self, actor: Actor, event_id: UUID) -> list[Rsvp]:
        """Organizers see everyone who answered."""
        await self._managed(actor, event_id)
        return await self._p.events.list_rsvps(event_id)

    async def check_in(
        self, actor: Actor, event_id: UUID, user_id: UUID, method: str
    ) -> Rsvp:
        """An organizer marks a person present."""
        event = await self._managed(actor, event_id)
        return await self._check_in(event, user_id, method)

    async def _check_in(self, event: Event, user_id: UUID, method: str) -> Rsvp:
        rsvp = await self._p.events.get_rsvp(event.id, user_id)
        if rsvp is None:
            raise ActivitiesNotFoundError()
        check_in(rsvp, method, self._p.clock.now(), event=event)
        await self._p.events.save_rsvp(rsvp)
        await award(
            self._p,
            await load_club(self._p, event.club_id),
            "attended",
            user_id,
            event.id,
        )
        return rsvp

    async def qr_token(self, actor: Actor, event_id: UUID) -> str:
        """The signed value the organizer shows as a QR code."""
        event = await self._managed(actor, event_id)
        return issue_token(event, self._p.secret, self._p.clock.now())

    async def check_in_qr(self, actor: Actor, token: str) -> Rsvp:
        """Self check-in: valid token and a going RSVP of the scanner."""
        p = self._p
        event = await p.events.get(peek_event_id(token))
        if event is None:
            raise InvalidCheckInTokenError()
        verify_token(token, event.id, p.secret, p.clock.now())
        rsvp = await p.events.get_rsvp(event.id, actor.user_id)
        if rsvp is None or rsvp.status != "going":
            raise InvalidCheckInTokenError()
        return await self._check_in(event, actor.user_id, "qr")

    async def assign_role(
        self, actor: Actor, event_id: UUID, user_id: UUID, role: str
    ) -> Rsvp:
        """Give a participant a role at the event."""
        await self._managed(actor, event_id)
        rsvp = await self._p.events.get_rsvp(event_id, user_id)
        if rsvp is None:
            raise ActivitiesNotFoundError()
        rsvp.event_role = role
        await self._p.events.save_rsvp(rsvp)
        return rsvp

    async def rate_due(self) -> int:
        """Ask attendees to rate events that ended two hours ago; once per event."""
        p = self._p
        now = p.clock.now()
        sent = 0
        for event in await p.events.list_all():
            if (
                event.status == EventStatus.CANCELLED
                or event.rating_requested_at is not None
                or now < rating_request_time(event)
            ):
                continue
            drafts = [
                note(
                    r.user_id,
                    NotificationType.EVENT_RATING_REQUEST,
                    {"event_id": str(event.id), "club_id": str(event.club_id)},
                    f"activities:event-rating:{event.id}:{r.user_id}",
                )
                for r in await p.events.list_rsvps(event.id)
                if r.checked_in_at is not None
            ]
            await p.notifier.send(drafts)
            event.rating_requested_at = now
            await p.events.save(event)
            sent += len(drafts)
        return sent
